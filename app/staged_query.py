"""
Staged query execution for complex SQL queries.

When a complex query times out, this module decomposes it by:
1. Extracting CTEs from the SQL
2. Identifying independent "leaf" CTEs (no CTE dependencies)
3. Executing leaf CTEs separately to materialize small result sets
4. Rebuilding the query with materialized CTEs as VALUES clauses
5. Executing the simplified query

This reduces load because:
- Reference table lookups (LABEXM, ICD10, etc.) run as fast micro-queries
- The optimizer handles small VALUES sets far more efficiently than subqueries
- The main query has fewer joins to resolve at execution time
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from app.db import (
    CancellableQuery,
    Database,
    QueryCancelledError,
    QueryResult,
)

logger = logging.getLogger(__name__)

# Maximum rows for a CTE to be materialized as VALUES
MAX_MATERIALIZE_ROWS = 10_000

# Per-stage timeout in milliseconds
STAGE_TIMEOUT_MS = 30_000


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedCTE:
    """A parsed CTE extracted from a SQL query."""

    name: str
    body: str
    col_list: tuple[str, ...] | None = None


@dataclass(frozen=True)
class StageResult:
    """Result of executing a single CTE stage."""

    name: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    row_count: int
    execution_time_ms: float


@dataclass(frozen=True)
class StagedQueryResult:
    """Result of a full staged query execution."""

    query_result: QueryResult
    stages_executed: int
    total_stage_time_ms: float
    materialized_ctes: tuple[str, ...]


# ---------------------------------------------------------------------------
# CTE Parser — balanced-parenthesis state machine
# ---------------------------------------------------------------------------


def _skip_ws(sql: str, pos: int) -> int:
    """Advance past whitespace."""
    while pos < len(sql) and sql[pos] in " \t\n\r":
        pos += 1
    return pos


def _read_identifier(sql: str, pos: int) -> tuple[str, int] | None:
    """Read a SQL identifier (plain or double-quoted).

    Returns (identifier, new_pos) or None.
    """
    pos = _skip_ws(sql, pos)
    if pos >= len(sql):
        return None

    if sql[pos] == '"':
        end = pos + 1
        while end < len(sql):
            if sql[end] == '"':
                if end + 1 < len(sql) and sql[end + 1] == '"':
                    end += 2  # escaped ""
                else:
                    return (sql[pos + 1 : end], end + 1)
            end += 1
        return None

    m = re.match(r"[a-zA-Z_]\w*", sql[pos:])
    if not m:
        return None
    return (m.group(0), pos + m.end())


def _find_matching_paren(sql: str, start: int) -> int | None:
    """Find matching ')' for '(' at *start*.

    Skips string literals, double-quoted identifiers,
    line comments (--) and block comments.

    Returns the index **after** the closing paren, or None.
    """
    depth = 1
    i = start + 1
    length = len(sql)

    while i < length and depth > 0:
        c = sql[i]

        if c == "'":
            i += 1
            while i < length:
                if sql[i] == "'":
                    if i + 1 < length and sql[i + 1] == "'":
                        i += 2
                    else:
                        break
                i += 1

        elif c == '"':
            i += 1
            while i < length:
                if sql[i] == '"':
                    if i + 1 < length and sql[i + 1] == '"':
                        i += 2
                    else:
                        break
                i += 1

        elif c == "-" and i + 1 < length and sql[i + 1] == "-":
            nl = sql.find("\n", i)
            i = nl if nl != -1 else length
            continue

        elif c == "/" and i + 1 < length and sql[i + 1] == "*":
            end = sql.find("*/", i + 2)
            i = end + 2 if end != -1 else length
            continue

        elif c == "(":
            depth += 1

        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1

        i += 1

    return None


def parse_ctes(sql: str) -> tuple[list[ParsedCTE], str] | None:
    """Parse CTEs from a SQL query.

    Returns ``(ctes, final_query)`` or ``None`` on parse error / no CTEs.
    Skips ``WITH RECURSIVE`` queries (not decomposable).
    """
    stripped = sql.strip()

    m = re.match(r"WITH\s+", stripped, re.IGNORECASE)
    if not m:
        return None

    # WITH RECURSIVE cannot be staged
    rest = stripped[m.end() :]
    if re.match(r"RECURSIVE\s+", rest, re.IGNORECASE):
        return None

    pos = m.end()
    ctes: list[ParsedCTE] = []

    while pos < len(stripped):
        ident = _read_identifier(stripped, pos)
        if not ident:
            break
        cte_name, pos = ident
        pos = _skip_ws(stripped, pos)

        # Optional column list: name (c1, c2) AS (...)
        col_list: tuple[str, ...] | None = None
        if pos < len(stripped) and stripped[pos] == "(":
            paren_end = _find_matching_paren(stripped, pos)
            if paren_end is None:
                return None
            after = _skip_ws(stripped, paren_end)
            if after < len(stripped) and re.match(
                r"AS\b", stripped[after:], re.IGNORECASE
            ):
                col_str = stripped[pos + 1 : paren_end - 1]
                col_list = tuple(
                    c.strip().strip('"') for c in col_str.split(",")
                )
                pos = after

        # AS keyword
        pos = _skip_ws(stripped, pos)
        as_m = re.match(r"AS\s*", stripped[pos:], re.IGNORECASE)
        if not as_m:
            break
        pos += as_m.end()

        # Opening paren of CTE body
        pos = _skip_ws(stripped, pos)
        if pos >= len(stripped) or stripped[pos] != "(":
            break

        body_end = _find_matching_paren(stripped, pos)
        if body_end is None:
            return None

        cte_body = stripped[pos + 1 : body_end - 1].strip()
        ctes.append(ParsedCTE(name=cte_name, body=cte_body, col_list=col_list))

        # Comma -> more CTEs, otherwise final query
        pos = _skip_ws(stripped, body_end)
        if pos < len(stripped) and stripped[pos] == ",":
            pos = _skip_ws(stripped, pos + 1)
        else:
            final_query = stripped[pos:].strip()
            if not final_query:
                return None
            return (ctes, final_query)

    return None


# ---------------------------------------------------------------------------
# Dependency analysis
# ---------------------------------------------------------------------------


def analyze_dependencies(
    ctes: list[ParsedCTE],
) -> dict[str, frozenset[str]]:
    """Map each CTE name to the set of *other* CTE names it references."""
    all_names = frozenset(c.name for c in ctes)
    deps: dict[str, frozenset[str]] = {}

    for cte in ctes:
        other = all_names - {cte.name}
        refs: set[str] = set()
        for name in other:
            pattern = r"\b" + re.escape(name) + r"\b"
            if re.search(pattern, cte.body, re.IGNORECASE):
                refs.add(name)
        deps[cte.name] = frozenset(refs)

    return deps


def find_leaf_ctes(deps: dict[str, frozenset[str]]) -> list[str]:
    """Return CTE names that depend on no other CTEs (execution-ready)."""
    return [name for name, references in deps.items() if not references]


# ---------------------------------------------------------------------------
# Query rebuilding with materialized VALUES
# ---------------------------------------------------------------------------


def _format_value(val: Any) -> str:
    """Format a Python value as a PostgreSQL literal.

    Only processes values that originated from the database (CTE results),
    so the attack surface is limited, but we still sanitize defensively.
    """
    import datetime
    import math
    from decimal import Decimal

    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, Decimal):
        return str(val)
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        if math.isnan(val):
            return "'NaN'::numeric"
        if math.isinf(val):
            return "'Infinity'::numeric" if val > 0 else "'-Infinity'::numeric"
        return str(val)
    if isinstance(val, (datetime.date, datetime.datetime)):
        return f"'{val.isoformat()}'"
    if isinstance(val, bytes):
        return f"'\\x{val.hex()}'::bytea"
    # Text: escape both backslashes and single quotes for safety
    text = str(val).replace("\\", "\\\\").replace("'", "''")
    return f"E'{text}'"


def _pg_type_hint(val: Any) -> str:
    """Return a PostgreSQL type cast for the first-row value."""
    import datetime
    import math
    from decimal import Decimal

    if val is None:
        return "::text"
    if isinstance(val, bool):
        return "::boolean"
    if isinstance(val, Decimal):
        return "::numeric"
    if isinstance(val, int):
        if val < -2_147_483_648 or val > 2_147_483_647:
            return "::bigint"
        return "::integer"
    if isinstance(val, float):
        return "::numeric"
    if isinstance(val, (datetime.datetime,)):
        return "::timestamp"
    if isinstance(val, (datetime.date,)):
        return "::date"
    if isinstance(val, bytes):
        return "::bytea"
    return "::text"


def _build_values_cte(
    name: str,
    columns: tuple[str, ...],
    rows: tuple[tuple[Any, ...], ...],
) -> str:
    """Build a CTE definition that uses a VALUES clause.

    The first row includes explicit type casts so PostgreSQL infers
    the correct column types for the remaining rows.
    """
    col_list = ", ".join(f'"{c}"' for c in columns)

    if not rows:
        # Empty result: SELECT ... WHERE FALSE preserves column names
        parts = ", ".join(f"NULL::text AS \"{c}\"" for c in columns)
        return f"{name} ({col_list}) AS (\n    SELECT {parts} WHERE FALSE\n  )"

    value_rows: list[str] = []
    for idx, row in enumerate(rows):
        vals: list[str] = []
        for col_idx, v in enumerate(row):
            formatted = _format_value(v)
            # Add type hint on first row only
            if idx == 0:
                formatted += _pg_type_hint(v)
            vals.append(formatted)
        value_rows.append(f"({', '.join(vals)})")

    values_str = ",\n      ".join(value_rows)
    return f"{name} ({col_list}) AS (\n    VALUES\n      {values_str}\n  )"


def rebuild_query(
    ctes: list[ParsedCTE],
    materialized: dict[str, StageResult],
    final_query: str,
) -> str:
    """Rebuild SQL, replacing materialized CTEs with VALUES clauses."""
    cte_parts: list[str] = []

    for cte in ctes:
        if cte.name in materialized:
            result = materialized[cte.name]
            cte_parts.append(
                _build_values_cte(cte.name, result.columns, result.rows)
            )
        else:
            if cte.col_list:
                col_str = ", ".join(f'"{c}"' for c in cte.col_list)
                cte_parts.append(
                    f"{cte.name} ({col_str}) AS (\n    {cte.body}\n  )"
                )
            else:
                cte_parts.append(f"{cte.name} AS (\n    {cte.body}\n  )")

    ctes_sql = ",\n  ".join(cte_parts)
    return f"WITH\n  {ctes_sql}\n{final_query}"


# ---------------------------------------------------------------------------
# Staged Executor
# ---------------------------------------------------------------------------


class StagedExecutor:
    """Execute complex CTE-based queries in stages to avoid timeouts.

    Usage::

        executor = StagedExecutor(db)
        if executor.can_decompose(sql):
            result = executor.execute_staged(sql, final_timeout_ms=120000, max_rows=2000)
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def can_decompose(self, sql: str) -> bool:
        """Return True if the SQL has leaf CTEs worth staging."""
        parsed = parse_ctes(sql)
        if not parsed:
            return False
        ctes, _ = parsed
        if len(ctes) < 2:
            return False
        deps = analyze_dependencies(ctes)
        return len(find_leaf_ctes(deps)) > 0

    def execute_staged(
        self,
        sql: str,
        final_timeout_ms: int,
        max_rows: int,
        stage_timeout_ms: int = STAGE_TIMEOUT_MS,
        max_materialize_rows: int = MAX_MATERIALIZE_ROWS,
        cancellable: CancellableQuery | None = None,
    ) -> StagedQueryResult | None:
        """Execute query in stages.

        1. Parse CTEs and find leaf CTEs (no inter-CTE dependencies).
        2. Execute each leaf CTE with *stage_timeout_ms*.
        3. If the result is small (<= *max_materialize_rows*), materialize
           it as a VALUES clause in the rebuilt query.
        4. Execute the rebuilt query with *final_timeout_ms*.

        Returns ``None`` if decomposition is impossible or produced no
        materialized CTEs (i.e. staging would not help).
        """
        parsed = parse_ctes(sql)
        if not parsed:
            return None

        ctes, final_query = parsed
        deps = analyze_dependencies(ctes)
        leaves = find_leaf_ctes(deps)

        if not leaves:
            return None

        logger.info(
            "Decomposing: %d CTEs, %d leaf CTEs %s",
            len(ctes),
            len(leaves),
            leaves,
        )

        materialized: dict[str, StageResult] = {}
        total_stage_time = 0.0

        for leaf_name in leaves:
            if cancellable is not None:
                cancellable.check_cancelled()

            cte = next(c for c in ctes if c.name == leaf_name)
            stage_sql = cte.body

            # Skip CTEs that are already VALUES (pre-materialized by optimizer)
            stripped_body = stage_sql.strip().upper()
            if stripped_body.startswith("VALUES"):
                logger.debug(
                    "Stage %s: already a VALUES clause, skipping", leaf_name,
                )
                continue

            logger.info("Executing stage: %s", leaf_name)
            start = time.perf_counter()

            try:
                if cancellable is not None:
                    stage_result_raw = cancellable.execute(
                        stage_sql,
                        None,
                        stage_timeout_ms,
                        max_materialize_rows + 1,
                    )
                else:
                    stage_result_raw = self._db.execute_query(
                        sql=stage_sql,
                        timeout_ms=stage_timeout_ms,
                        max_rows=max_materialize_rows + 1,
                    )
            except QueryCancelledError:
                raise
            except Exception as exc:
                logger.warning("Stage %s failed: %s", leaf_name, exc)
                continue  # keep original CTE body

            elapsed = (time.perf_counter() - start) * 1000
            total_stage_time += elapsed

            if stage_result_raw.row_count <= max_materialize_rows:
                # Use CTE's explicit column list if available (cursor
                # column names for VALUES bodies are generic "column1" etc.)
                columns = (
                    cte.col_list
                    if cte.col_list
                    else tuple(stage_result_raw.columns)
                )
                materialized[leaf_name] = StageResult(
                    name=leaf_name,
                    columns=columns,
                    rows=tuple(
                        tuple(r) for r in stage_result_raw.rows
                    ),
                    row_count=stage_result_raw.row_count,
                    execution_time_ms=round(elapsed, 2),
                )
                logger.info(
                    "Stage %s: %d rows in %.0fms (materialized)",
                    leaf_name,
                    stage_result_raw.row_count,
                    elapsed,
                )
            else:
                logger.info(
                    "Stage %s: %d+ rows — too large, keeping as CTE",
                    leaf_name,
                    stage_result_raw.row_count,
                )

        if not materialized:
            logger.info("No CTEs materialized; staged execution skipped")
            return None

        # Rebuild query with materialized CTEs
        rebuilt_sql = rebuild_query(ctes, materialized, final_query)
        logger.info(
            "Rebuilt query: %d/%d CTEs materialized, final timeout %dms",
            len(materialized),
            len(ctes),
            final_timeout_ms,
        )

        if cancellable is not None:
            cancellable.check_cancelled()
            final_result = cancellable.execute(
                rebuilt_sql, None, final_timeout_ms, max_rows,
            )
        else:
            final_result = self._db.execute_query(
                sql=rebuilt_sql,
                timeout_ms=final_timeout_ms,
                max_rows=max_rows,
            )

        return StagedQueryResult(
            query_result=final_result,
            stages_executed=len(materialized),
            total_stage_time_ms=round(total_stage_time, 2),
            materialized_ctes=tuple(materialized.keys()),
        )
