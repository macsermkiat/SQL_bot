"""
SQL Guard - CRITICAL safety validation for generated SQL.

Multi-layer validation using sqlglot:
1. Keyword blocklist (fast)
2. Statement type (only SELECT allowed)
3. Table validation (must exist in catalog)
4. Column validation (must exist in table)
5. PHI blocking (no PHI columns in SELECT output)
6. LIMIT enforcement (non-aggregate queries)
7. No SELECT * (explicit columns required)
8. Join confidence validation (warn on low-confidence joins)

Integration with schema_catalog for enhanced schema grounding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

if TYPE_CHECKING:
    from app.schema_catalog import SchemaCatalog

# Forbidden SQL keywords - reject immediately if found
FORBIDDEN_KEYWORDS: frozenset[str] = frozenset({
    "INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER",
    "TRUNCATE", "GRANT", "REVOKE", "COPY", "VACUUM", "ANALYZE",
    "CALL", "DO", "MERGE", "EXECUTE", "PREPARE", "DEALLOCATE",
    "COMMIT", "ROLLBACK", "SAVEPOINT", "LOCK", "UNLOCK",
    "SET ROLE", "RESET", "DISCARD", "LOAD", "UNLOAD",
})

# PHI columns that must NEVER appear in SELECT output
PHI_COLUMNS: frozenset[str] = frozenset({
    # Patient identifiers
    "hn", "cid", "passport", "mrn", "national_id", "idcard", "pid",
    # Names
    "fname", "lname", "mname", "pname", "name", "fullname",
    "firstname", "lastname", "middlename", "prename",
    # Contact info
    "phone", "mobile", "tel", "telephone", "email", "fax",
    # Address
    "address", "addrpart", "moo", "road", "tambon", "amphur",
    "province", "zipcode", "postcode", "homeaddr", "workaddr",
    # Date of birth (exact)
    "dob", "birthdate", "birthday", "bdate",
    # Other quasi-identifiers
    "ssn", "social_security", "insurance_id", "member_id",
})


class SQLGuardError(Exception):
    """Base exception for SQL guard errors."""
    pass


class ForbiddenStatementError(SQLGuardError):
    """Non-SELECT statement detected."""
    pass


class ForbiddenKeywordError(SQLGuardError):
    """Dangerous SQL keyword detected."""
    pass


class UnknownTableError(SQLGuardError):
    """Table not found in catalog."""
    pass


class UnknownColumnError(SQLGuardError):
    """Column not found in table."""
    pass


class PHIExposureError(SQLGuardError):
    """PHI column in SELECT output."""
    pass


class MissingLimitError(SQLGuardError):
    """Non-aggregate query without LIMIT."""
    pass


class SelectStarError(SQLGuardError):
    """SELECT * is not allowed."""
    pass


class SQLParseError(SQLGuardError):
    """Failed to parse SQL."""
    pass


@dataclass
class JoinWarning:
    """Warning about a potentially problematic join."""
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    confidence: str
    message: str
    suggested_alternative: str | None = None


@dataclass
class ValidationResult:
    """Result of SQL validation."""
    valid: bool
    error: str | None = None
    error_type: str | None = None
    tables_used: list[str] | None = None
    columns_used: dict[str, list[str]] | None = None
    all_columns: dict[str, list[str]] | None = None  # All columns (not just SELECT)
    has_aggregation: bool = False
    has_limit: bool = False
    limit_value: int | None = None
    phi_columns_found: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    join_warnings: list[JoinWarning] = field(default_factory=list)


def _quick_keyword_check(sql: str) -> str | None:
    """
    Fast keyword blocklist check before parsing.
    Returns error message if forbidden keyword found, None if OK.
    """
    upper_sql = sql.upper()

    # Remove string literals to avoid false positives
    # Replace strings with empty placeholders
    cleaned = re.sub(r"'[^']*'", "''", upper_sql)
    cleaned = re.sub(r'"[^"]*"', '""', cleaned)

    for keyword in FORBIDDEN_KEYWORDS:
        # Use word boundary to avoid matching substrings
        pattern = rf"\b{keyword}\b"
        if re.search(pattern, cleaned):
            return f"Forbidden keyword: {keyword}"

    return None


def _extract_tables(parsed: exp.Expression) -> set[str]:
    """Extract all table names from parsed SQL."""
    tables = set()
    for table in parsed.find_all(exp.Table):
        if table.name:
            tables.add(table.name.upper())
    return tables


def _extract_table_aliases(parsed: exp.Expression) -> dict[str, str]:
    """
    Extract table alias mappings from parsed SQL.
    Returns dict of alias -> table_name (both uppercase).
    """
    aliases: dict[str, str] = {}
    for table in parsed.find_all(exp.Table):
        if table.name:
            table_name = table.name.upper()
            # Check for alias
            if table.alias:
                alias = table.alias.upper()
                aliases[alias] = table_name
            # Also map the table name to itself for convenience
            aliases[table_name] = table_name
    return aliases


def _resolve_column_tables(
    columns: dict[str, list[str]],
    aliases: dict[str, str],
) -> dict[str, list[str]]:
    """
    Resolve table aliases in column dict to actual table names.
    """
    resolved: dict[str, list[str]] = {}
    for table, cols in columns.items():
        if table in ("_UNKNOWN_", "_STAR_"):
            resolved[table] = cols
        else:
            # Resolve alias to real table name
            real_table = aliases.get(table.upper(), table.upper())
            if real_table not in resolved:
                resolved[real_table] = []
            resolved[real_table].extend(cols)
    return resolved


def _is_inside_aggregate(expr: exp.Expression) -> bool:
    """Check if expression is inside an aggregate function."""
    agg_types = (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max, exp.ArrayAgg)
    parent = expr.parent
    while parent:
        if isinstance(parent, agg_types):
            return True
        parent = parent.parent
    return False


def _extract_output_columns(parsed: exp.Expression) -> dict[str, list[str]]:
    """
    Extract columns that appear in the SELECT output.
    Only collects columns that would be visible in results (not inside aggregates).
    Returns dict of table_name -> [column_names].
    """
    columns: dict[str, list[str]] = {}

    # Find the outermost SELECT(s)
    def collect_from_select(select: exp.Select) -> None:
        for expr in select.expressions:
            _collect_output_columns(expr, columns)

    # Handle different statement types
    if isinstance(parsed, exp.Select):
        collect_from_select(parsed)
    elif isinstance(parsed, exp.Union):
        # For UNION, check all SELECT parts
        for select in parsed.find_all(exp.Select):
            collect_from_select(select)
    elif hasattr(parsed, 'this') and isinstance(parsed.this, exp.Select):
        # CTE wrapper
        collect_from_select(parsed.this)

    return columns


def _collect_output_columns(
    expr: exp.Expression,
    columns: dict[str, list[str]],
    inside_aggregate: bool = False,
) -> None:
    """
    Collect columns from SELECT expression that appear in output.
    Columns inside aggregate functions are NOT collected (they don't expose individual values).
    """
    # Check if we're entering an aggregate
    agg_types = (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max, exp.ArrayAgg)
    if isinstance(expr, agg_types):
        # Don't collect columns inside aggregates - they don't expose individual values
        return

    if isinstance(expr, exp.Column):
        # Only add if not inside an aggregate
        if not inside_aggregate:
            table_name = expr.table.upper() if expr.table else "_UNKNOWN_"
            col_name = expr.name.lower()
            if table_name not in columns:
                columns[table_name] = []
            if col_name not in columns[table_name]:
                columns[table_name].append(col_name)
    elif isinstance(expr, exp.Star):
        # SELECT * detected
        table_name = "_STAR_"
        if hasattr(expr, 'table') and expr.table:
            table_name = expr.table.upper()
        if table_name not in columns:
            columns[table_name] = []
        if "*" not in columns[table_name]:
            columns[table_name].append("*")
    else:
        # Recurse into child expressions
        for child in expr.iter_expressions():
            _collect_output_columns(child, columns, inside_aggregate)


def _extract_all_columns(parsed: exp.Expression) -> dict[str, list[str]]:
    """
    Extract ALL column references from the entire SQL statement.
    Includes columns in SELECT, WHERE, JOIN, GROUP BY, ORDER BY, etc.
    Returns dict of table_name -> [column_names].
    """
    columns: dict[str, list[str]] = {}

    for col in parsed.find_all(exp.Column):
        table_name = col.table.upper() if col.table else "_UNKNOWN_"
        col_name = col.name.lower()
        if table_name not in columns:
            columns[table_name] = []
        if col_name not in columns[table_name]:
            columns[table_name].append(col_name)

    return columns


def _resolve_unknown_columns_to_tables(
    columns: dict[str, list[str]],
    parsed: exp.Expression,
) -> dict[str, list[str]]:
    """
    Resolve columns marked as _UNKNOWN_ to their source tables.

    For each SELECT subquery, if there's exactly one table in FROM,
    unqualified columns must belong to that table.
    """
    unknown_cols = columns.get("_UNKNOWN_", [])
    if not unknown_cols:
        return columns

    # Build a map of subquery -> single table (if applicable)
    # For each SELECT with a single FROM table, unqualified columns belong to that table
    resolved = {k: list(v) for k, v in columns.items()}

    for select in parsed.find_all(exp.Select):
        # Get tables in this SELECT's FROM clause
        from_tables = []
        from_clause = select.args.get("from")
        if from_clause:
            for table in from_clause.find_all(exp.Table):
                if table.name:
                    # Use alias if available, otherwise table name
                    name = table.alias or table.name
                    from_tables.append(name.upper())

        # Also check joins
        for join in select.args.get("joins") or []:
            for table in join.find_all(exp.Table):
                if table.name:
                    name = table.alias or table.name
                    from_tables.append(name.upper())

        # If exactly one table in this SELECT's scope, assign unknown columns
        if len(from_tables) == 1:
            single_table = from_tables[0]

            # Find unqualified columns in this SELECT
            for col in select.find_all(exp.Column):
                if not col.table and col.name.lower() in unknown_cols:
                    col_name = col.name.lower()
                    if single_table not in resolved:
                        resolved[single_table] = []
                    if col_name not in resolved[single_table]:
                        resolved[single_table].append(col_name)
                    # Remove from unknown
                    if col_name in resolved.get("_UNKNOWN_", []):
                        resolved["_UNKNOWN_"].remove(col_name)

    # Clean up empty _UNKNOWN_
    if "_UNKNOWN_" in resolved and not resolved["_UNKNOWN_"]:
        del resolved["_UNKNOWN_"]

    return resolved


def _has_aggregation(parsed: exp.Expression) -> bool:
    """Check if query has aggregate functions or GROUP BY."""
    # Check for aggregate functions
    agg_funcs = (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)
    for _ in parsed.find_all(*agg_funcs):
        return True

    # Check for GROUP BY
    for select in parsed.find_all(exp.Select):
        if select.args.get("group"):
            return True

    # Check for DISTINCT
    for select in parsed.find_all(exp.Select):
        if select.args.get("distinct"):
            return True

    return False


@dataclass
class ExtractedJoin:
    """A join extracted from SQL."""
    left_table: str
    left_column: str
    right_table: str
    right_column: str


def _extract_joins(
    parsed: exp.Expression,
    table_aliases: dict[str, str],
) -> list[ExtractedJoin]:
    """
    Extract all explicit joins from parsed SQL.

    Looks for:
    - JOIN ... ON table1.col = table2.col
    - WHERE table1.col = table2.col (implicit joins)

    Returns list of ExtractedJoin with resolved table names (not aliases).
    """
    joins: list[ExtractedJoin] = []

    # Find explicit JOIN conditions
    for join_expr in parsed.find_all(exp.Join):
        on_clause = join_expr.args.get("on")
        if on_clause:
            _extract_eq_joins(on_clause, table_aliases, joins)

    # Find implicit joins in WHERE clause
    for select in parsed.find_all(exp.Select):
        where_clause = select.args.get("where")
        if where_clause:
            _extract_eq_joins(where_clause.this, table_aliases, joins)

    return joins


def _extract_eq_joins(
    expr: exp.Expression,
    table_aliases: dict[str, str],
    joins: list[ExtractedJoin],
) -> None:
    """
    Extract equality conditions that look like joins.

    Only captures table.col = table.col patterns where both sides
    have explicit table references and different tables.
    """
    if isinstance(expr, exp.EQ):
        left = expr.left
        right = expr.right

        # Both sides must be column references
        if isinstance(left, exp.Column) and isinstance(right, exp.Column):
            # Both must have table qualifiers
            if left.table and right.table:
                left_table = table_aliases.get(
                    left.table.upper(), left.table.upper()
                )
                right_table = table_aliases.get(
                    right.table.upper(), right.table.upper()
                )

                # Must be joining different tables
                if left_table != right_table:
                    joins.append(ExtractedJoin(
                        left_table=left_table,
                        left_column=left.name.lower(),
                        right_table=right_table,
                        right_column=right.name.lower(),
                    ))

    # Recurse into AND conditions
    elif isinstance(expr, exp.And):
        _extract_eq_joins(expr.left, table_aliases, joins)
        _extract_eq_joins(expr.right, table_aliases, joins)


def _validate_joins(
    joins: list[ExtractedJoin],
    catalog: "SchemaCatalog",
) -> list[JoinWarning]:
    """
    Validate extracted joins against schema catalog.

    Returns list of warnings for:
    - Low confidence joins (heuristic)
    - Joins with explicit warnings in schema (e.g., home_key_override)
    - Unknown joins not in catalog
    """
    warnings: list[JoinWarning] = []

    for join in joins:
        validation = catalog.validate_join(
            table_a=join.left_table,
            column_a=join.left_column,
            table_b=join.right_table,
            column_b=join.right_column,
        )

        # Add warning for low confidence
        if validation.confidence == "heuristic":
            # Try to find a better alternative
            best = catalog.get_best_join(join.left_table, join.right_table)
            suggested = None
            if best and best.total_score > 25:  # Better than heuristic
                step = best.steps[0]
                suggested = (
                    f"{step.from_table}.{step.from_column} = "
                    f"{step.to_table}.{step.to_column}"
                )

            warnings.append(JoinWarning(
                from_table=join.left_table,
                from_column=join.left_column,
                to_table=join.right_table,
                to_column=join.right_column,
                confidence="heuristic",
                message="Low confidence join - consider using a verified join path",
                suggested_alternative=suggested,
            ))

        # Add warning for joins with explicit warnings in schema
        for w in validation.warnings:
            warnings.append(JoinWarning(
                from_table=join.left_table,
                from_column=join.left_column,
                to_table=join.right_table,
                to_column=join.right_column,
                confidence=validation.confidence,
                message=w,
                suggested_alternative=None,
            ))

        # Warning for unknown joins
        if not validation.valid:
            warnings.append(JoinWarning(
                from_table=join.left_table,
                from_column=join.left_column,
                to_table=join.right_table,
                to_column=join.right_column,
                confidence="unknown",
                message="Join not found in schema catalog",
                suggested_alternative=None,
            ))

    return warnings


def _get_limit_value(parsed: exp.Expression) -> int | None:
    """Get LIMIT value if present."""
    for limit in parsed.find_all(exp.Limit):
        if limit.expression:
            try:
                # Handle different ways the limit value might be stored
                if hasattr(limit.expression, 'this'):
                    return int(limit.expression.this)
                return int(str(limit.expression))
            except (ValueError, AttributeError, TypeError):
                pass
    return None


def _check_phi_in_select(
    columns: dict[str, list[str]],
    catalog: "SchemaCatalog | None" = None,
) -> tuple[str | None, list[str]]:
    """
    Check if any PHI columns are in the SELECT output.

    Args:
        columns: Dict of table_name -> [column_names] from SELECT
        catalog: Optional catalog for enhanced PHI detection

    Returns:
        Tuple of (error_message, phi_columns_found)
        error_message is None if OK
    """
    phi_found: list[str] = []

    for table, cols in columns.items():
        for col in cols:
            col_lower = col.lower()

            # Check hardcoded PHI list
            if col_lower in PHI_COLUMNS:
                phi_found.append(f"{table}.{col}" if table != "_UNKNOWN_" else col)
                continue

            # Check catalog's PHI markers (more comprehensive)
            if catalog and table not in ("_UNKNOWN_", "_STAR_"):
                table_obj = catalog.get_table(table)
                if table_obj and col_lower in table_obj.columns:
                    if table_obj.columns[col_lower].is_phi:
                        phi_found.append(f"{table}.{col}")

    if phi_found:
        return (
            f"PHI column(s) cannot be included in SELECT output: {', '.join(phi_found)}",
            phi_found,
        )
    return None, []


def _check_select_star(columns: dict[str, list[str]]) -> str | None:
    """
    Check for SELECT * which is not allowed.
    Returns error message if found, None if OK.
    """
    for table, cols in columns.items():
        if "*" in cols:
            if table == "_STAR_":
                return "SELECT * is not allowed. Please specify explicit column names."
            return f"SELECT {table}.* is not allowed. Please specify explicit column names."
    return None


def validate_sql(
    sql: str,
    catalog: SchemaCatalog | None = None,
    max_rows: int = 2000,
    strict_catalog_check: bool = False,
    validate_joins: bool = True,
) -> ValidationResult:
    """
    Validate SQL against all safety rules.

    Args:
        sql: SQL query to validate
        catalog: Schema catalog for table/column validation
        max_rows: Maximum allowed LIMIT value
        strict_catalog_check: If True, require all tables/columns in catalog
        validate_joins: If True, validate join confidence (requires catalog)

    Returns:
        ValidationResult with validation status and details
    """
    # Layer 1: Quick keyword blocklist
    keyword_error = _quick_keyword_check(sql)
    if keyword_error:
        return ValidationResult(
            valid=False,
            error=keyword_error,
            error_type="ForbiddenKeywordError",
        )

    # Layer 2: Parse SQL
    try:
        parsed = sqlglot.parse_one(sql, dialect="postgres")
    except ParseError as e:
        return ValidationResult(
            valid=False,
            error=f"SQL parse error: {e}",
            error_type="SQLParseError",
        )

    # Layer 3: Statement type - only SELECT allowed
    is_valid_select = False
    if isinstance(parsed, exp.Select):
        is_valid_select = True
    elif isinstance(parsed, exp.Union):
        is_valid_select = True  # UNION of SELECTs is OK
    elif hasattr(parsed, 'this') and isinstance(parsed.this, exp.Select):
        is_valid_select = True  # CTE wrapper is OK

    if not is_valid_select:
        return ValidationResult(
            valid=False,
            error=f"Only SELECT statements are allowed. Got: {type(parsed).__name__}",
            error_type="ForbiddenStatementError",
        )

    # Extract metadata
    tables_used = _extract_tables(parsed)
    table_aliases = _extract_table_aliases(parsed)
    select_columns = _extract_output_columns(parsed)
    all_columns = _extract_all_columns(parsed)
    has_agg = _has_aggregation(parsed)
    limit_val = _get_limit_value(parsed)
    warnings: list[str] = []

    # Resolve aliases for catalog validation
    select_columns_resolved = _resolve_column_tables(select_columns, table_aliases)
    all_columns_resolved = _resolve_column_tables(all_columns, table_aliases)

    # Resolve unknown columns to their source tables
    all_columns_resolved = _resolve_unknown_columns_to_tables(all_columns_resolved, parsed)
    select_columns_resolved = _resolve_unknown_columns_to_tables(select_columns_resolved, parsed)

    # Layer 4: Check for SELECT *
    star_error = _check_select_star(select_columns)
    if star_error:
        return ValidationResult(
            valid=False,
            error=star_error,
            error_type="SelectStarError",
            tables_used=list(tables_used),
        )

    # Layer 5: Check PHI in SELECT output (use resolved columns for better catalog lookup)
    phi_error, phi_found = _check_phi_in_select(select_columns_resolved, catalog)
    if phi_error:
        return ValidationResult(
            valid=False,
            error=phi_error,
            error_type="PHIExposureError",
            tables_used=list(tables_used),
            phi_columns_found=phi_found,
        )

    # Layer 6: Catalog validation (if provided)
    if catalog:
        # Use resolved columns (with aliases mapped to real tables) for validation
        columns_for_validation: dict[str, list[str]] = {}
        for table, cols in all_columns_resolved.items():
            if table not in ("_UNKNOWN_", "_STAR_"):
                columns_for_validation[table.upper()] = cols

        if strict_catalog_check:
            invalid_tables, invalid_cols = catalog.validate_sql_references(
                tables=list(tables_used),
                columns=columns_for_validation,
            )

            if invalid_tables:
                return ValidationResult(
                    valid=False,
                    error=f"Unknown table(s): {', '.join(invalid_tables)}",
                    error_type="UnknownTableError",
                    tables_used=list(tables_used),
                    all_columns=all_columns_resolved,
                )

            if invalid_cols:
                return ValidationResult(
                    valid=False,
                    error=f"Unknown column(s): {', '.join(invalid_cols)}",
                    error_type="UnknownColumnError",
                    tables_used=list(tables_used),
                    all_columns=all_columns_resolved,
                )
        else:
            # Non-strict mode: add warnings for unknown tables/columns
            for table in tables_used:
                if not catalog.table_exists(table):
                    warnings.append(f"Table '{table}' not found in catalog")

    # Layer 7: LIMIT enforcement for non-aggregate queries
    if not has_agg:
        if limit_val is None:
            return ValidationResult(
                valid=False,
                error=f"Non-aggregate queries must include LIMIT (max {max_rows} rows)",
                error_type="MissingLimitError",
                tables_used=list(tables_used),
                columns_used=select_columns_resolved,
                all_columns=all_columns_resolved,
                has_aggregation=has_agg,
                warnings=warnings,
            )
        if limit_val > max_rows:
            return ValidationResult(
                valid=False,
                error=f"LIMIT {limit_val} exceeds maximum allowed ({max_rows})",
                error_type="MissingLimitError",
                tables_used=list(tables_used),
                columns_used=select_columns_resolved,
                all_columns=all_columns_resolved,
                has_aggregation=has_agg,
                has_limit=True,
                limit_value=limit_val,
                warnings=warnings,
            )

    # Layer 8: Join validation (confidence and warnings)
    join_warnings: list[JoinWarning] = []
    if catalog and validate_joins:
        extracted_joins = _extract_joins(parsed, table_aliases)
        if extracted_joins:
            join_warnings = _validate_joins(extracted_joins, catalog)
            # Add readable warnings to the general warnings list (deduplicated)
            seen_warnings: set[str] = set()
            for jw in join_warnings:
                join_key = f"{jw.from_table}.{jw.from_column}={jw.to_table}.{jw.to_column}"

                if jw.confidence == "heuristic" and jw.message.startswith("Low confidence"):
                    # Generic low-confidence warning
                    msg = f"Low-confidence join: {jw.from_table}.{jw.from_column} = {jw.to_table}.{jw.to_column}"
                    if jw.suggested_alternative:
                        msg += f" (consider: {jw.suggested_alternative})"
                    if msg not in seen_warnings:
                        warnings.append(msg)
                        seen_warnings.add(msg)
                elif jw.confidence == "unknown":
                    msg = (
                        f"Unverified join: {jw.from_table}.{jw.from_column} = "
                        f"{jw.to_table}.{jw.to_column}"
                    )
                    if msg not in seen_warnings:
                        warnings.append(msg)
                        seen_warnings.add(msg)
                elif jw.message:
                    # Schema-specific warning (home_key_override, etc.)
                    msg = f"Join warning ({jw.from_table}.{jw.from_column}): {jw.message}"
                    if msg not in seen_warnings:
                        warnings.append(msg)
                        seen_warnings.add(msg)

    # All checks passed
    return ValidationResult(
        valid=True,
        tables_used=list(tables_used),
        columns_used=select_columns_resolved,
        all_columns=all_columns_resolved,
        has_aggregation=has_agg,
        has_limit=limit_val is not None,
        limit_value=limit_val,
        warnings=warnings,
        join_warnings=join_warnings,
    )


def guard_sql(
    sql: str,
    catalog: SchemaCatalog | None = None,
    max_rows: int = 2000,
    strict_catalog_check: bool = False,
    validate_joins: bool = True,
) -> str:
    """
    Validate SQL and raise appropriate exception if invalid.

    Args:
        sql: SQL query to validate
        catalog: Schema catalog for table/column validation
        max_rows: Maximum allowed LIMIT value
        strict_catalog_check: If True, require all tables/columns in catalog
        validate_joins: If True, validate join confidence (requires catalog)

    Returns:
        The original SQL if valid

    Raises:
        SQLGuardError subclass if validation fails
    """
    result = validate_sql(sql, catalog, max_rows, strict_catalog_check, validate_joins)

    if result.valid:
        return sql

    error_classes = {
        "ForbiddenKeywordError": ForbiddenKeywordError,
        "ForbiddenStatementError": ForbiddenStatementError,
        "SQLParseError": SQLParseError,
        "SelectStarError": SelectStarError,
        "PHIExposureError": PHIExposureError,
        "UnknownTableError": UnknownTableError,
        "UnknownColumnError": UnknownColumnError,
        "MissingLimitError": MissingLimitError,
    }

    error_class = error_classes.get(result.error_type, SQLGuardError)
    raise error_class(result.error)


def validate_with_catalog(
    sql: str,
    max_rows: int = 2000,
    strict: bool = True,
    validate_joins: bool = True,
) -> ValidationResult:
    """
    Validate SQL using the enhanced schema catalog.

    This is a convenience function that loads the catalog automatically.

    Args:
        sql: SQL query to validate
        max_rows: Maximum allowed LIMIT value
        strict: If True, reject unknown tables/columns
        validate_joins: If True, validate join confidence

    Returns:
        ValidationResult with validation status and details
    """
    from app.schema_catalog import get_schema_catalog

    catalog = get_schema_catalog()
    return validate_sql(
        sql, catalog, max_rows,
        strict_catalog_check=strict,
        validate_joins=validate_joins,
    )


def guard_with_catalog(
    sql: str,
    max_rows: int = 2000,
    strict: bool = True,
    validate_joins: bool = True,
) -> str:
    """
    Validate SQL using the enhanced schema catalog, raising on errors.

    This is a convenience function that loads the catalog automatically.

    Args:
        sql: SQL query to validate
        max_rows: Maximum allowed LIMIT value
        strict: If True, reject unknown tables/columns
        validate_joins: If True, validate join confidence

    Returns:
        The original SQL if valid

    Raises:
        SQLGuardError subclass if validation fails
    """
    from app.schema_catalog import get_schema_catalog

    catalog = get_schema_catalog()
    return guard_sql(
        sql, catalog, max_rows,
        strict_catalog_check=strict,
        validate_joins=validate_joins,
    )
