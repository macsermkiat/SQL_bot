"""
SQL query optimizer for preventing timeout-causing patterns.

Primary optimization: Flatten Leaf CTE Scans
When leaf CTEs scan large tables with date range filters, they create
CTE optimization fences in PostgreSQL (materialized before downstream
filters apply). By flattening these into downstream CTEs, PostgreSQL
can freely choose JOIN order and push small-table filters through.

Example - BEFORE (CTE fence forces sequential scan of LVST):
    WITH lvst_2024 AS (
        SELECT "labno", "hn" FROM LVST WHERE date range
    ),
    hba1c AS (
        SELECT ... FROM lvst_2024 l24
        JOIN LVSTEXM lexm ON l24."labno" = lexm."labno"
        JOIN labcodes hl ON lexm."labexm" = hl."labexm"
    )

AFTER (no fence, PG starts from small labcodes table):
    WITH hba1c AS (
        SELECT ... FROM LVST l24
        JOIN LVSTEXM lexm ON l24."labno" = lexm."labno"
        JOIN labcodes hl ON lexm."labexm" = hl."labexm"
        WHERE l24."lvstdate" >= '2024-01-01' AND l24."lvstdate" < '2025-01-01'
    )
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass

from app.staged_query import (
    ParsedCTE,
    analyze_dependencies,
    find_leaf_ctes,
    parse_ctes,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex patterns for CTE body analysis
# ---------------------------------------------------------------------------

# Match: [alias.]"col" >= 'YYYY-MM-DD' AND [alias.]"col" < 'YYYY-MM-DD'
_DATE_RANGE_RE = re.compile(
    r"(?:(\w+)\s*\.\s*)?"  # optional alias (group 1)
    r'"(\w+)"\s*>=\s*\'(\d{4}-\d{2}-\d{2})\''  # "col" >= 'start' (groups 2,3)
    r"\s+AND\s+"
    r"(?:(\w+)\s*\.\s*)?"  # optional alias (group 4)
    r'"(\w+)"\s*<\s*\'(\d{4}-\d{2}-\d{2})\'',  # "col" < 'end' (groups 5,6)
    re.IGNORECASE,
)

# Match: FROM "KCMH_HIS"."TABLE" [alias]
_SQL_KEYWORDS = frozenset({
    "WHERE", "JOIN", "INNER", "LEFT", "RIGHT", "OUTER", "CROSS", "FULL",
    "ON", "AND", "OR", "NOT", "ORDER", "GROUP", "HAVING", "LIMIT",
    "UNION", "EXCEPT", "INTERSECT", "AS", "SET", "INTO", "VALUES",
})
_FROM_TABLE_RE = re.compile(
    r"FROM\s+"
    r'(?:("?\w+"?)\s*\.\s*)?'  # optional schema (group 1)
    r'("?\w+"?)'  # table (group 2)
    r"(?:\s+(?:AS\s+)?(\w+))?",  # optional alias (group 3)
    re.IGNORECASE,
)

# Match: SELECT [DISTINCT] <columns> FROM
_SELECT_RE = re.compile(
    r"SELECT\s+(DISTINCT\s+)?(.*?)\s+FROM\b",
    re.IGNORECASE | re.DOTALL,
)


# ---------------------------------------------------------------------------
# Leaf CTE analysis
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _LeafInfo:
    """Metadata extracted from a leaf CTE for optimization."""

    schema_name: str | None  # e.g. "KCMH_HIS"
    base_table: str  # e.g. "LVST"
    table_alias: str | None  # e.g. "lv" or None
    date_col: str  # e.g. "lvstdate"
    date_alias: str | None  # alias prefix on date col, e.g. "lv"
    date_start: str  # e.g. "2024-01-01"
    date_end: str  # e.g. "2025-01-01"
    select_clause: str  # e.g. '"labno", "hn"'
    is_distinct: bool
    fingerprint: str  # normalized body for grouping
    is_simple_scan: bool  # no JOINs, no subqueries


def _analyze_leaf(body: str) -> _LeafInfo | None:
    """Extract optimization-relevant metadata from a leaf CTE body.

    Returns None if the CTE is not a candidate for optimization
    (no date range filter, no recognizable table, etc.).
    """
    table_m = _FROM_TABLE_RE.search(body)
    if not table_m:
        return None

    # Filter out SQL keywords captured as alias
    table_alias = table_m.group(3)
    if table_alias and table_alias.upper() in _SQL_KEYWORDS:
        table_alias = None
    schema_name = table_m.group(1)
    if schema_name:
        schema_name = schema_name.strip('"')
    base_table = table_m.group(2).strip('"')

    date_m = _DATE_RANGE_RE.search(body)
    if not date_m:
        return None
    # Ensure same column name in both halves
    if date_m.group(2) != date_m.group(5):
        return None

    select_m = _SELECT_RE.search(body)
    if not select_m:
        return None

    # Build fingerprint: replace all date literals so identical-except-dates
    # CTEs get the same fingerprint
    fp = re.sub(r"\d{4}-\d{2}-\d{2}", "____", body)
    fp = " ".join(fp.split())

    # Check if this is a simple scan (no JOINs, no subqueries, no GROUP BY)
    upper = body.upper()
    is_simple = (
        not re.search(r"\bJOIN\b", upper)
        and not re.search(r"\(\s*SELECT\b", upper)
        and not re.search(r"\bGROUP\s+BY\b", upper)
    )

    return _LeafInfo(
        schema_name=schema_name,
        base_table=base_table,
        table_alias=table_alias,
        date_col=date_m.group(2),
        date_alias=date_m.group(1),  # alias prefix on date column
        date_start=date_m.group(3),
        date_end=date_m.group(6),
        select_clause=select_m.group(2).strip(),
        is_distinct=bool(select_m.group(1)),
        fingerprint=fp,
        is_simple_scan=is_simple,
    )


# ---------------------------------------------------------------------------
# Flatten optimization (primary strategy)
# ---------------------------------------------------------------------------


def _flatten_from_reference(
    leaf_name: str,
    leaf_info: _LeafInfo,
    downstream_body: str,
) -> str | None:
    """Replace FROM leaf_name with FROM base_table and add date conditions.

    Transforms:
        FROM lvst_2024 l24  -->  FROM "KCMH_HIS"."LVST" l24
    And injects:
        WHERE l24."lvstdate" >= '2024-01-01' AND l24."lvstdate" < '2025-01-01'
    """
    # Find FROM leaf_name [alias] in the downstream body
    from_re = re.compile(
        rf"\bFROM\s+{re.escape(leaf_name)}\b(?:\s+(\w+))?",
        re.IGNORECASE,
    )
    m = from_re.search(downstream_body)
    if not m:
        return None

    # Get the alias used for the leaf CTE in the downstream query
    alias = m.group(1)
    if alias and alias.upper() in _SQL_KEYWORDS:
        alias = None
    if not alias:
        # Generate a short alias from the table name
        alias = leaf_info.base_table.lower()[:3]

    # Replace FROM clause with actual base table
    if leaf_info.schema_name:
        table_ref = f'"{leaf_info.schema_name}"."{leaf_info.base_table}"'
    else:
        table_ref = f'"{leaf_info.base_table}"'
    new_from = f"FROM {table_ref} {alias}"
    new_body = downstream_body[: m.start()] + new_from + downstream_body[m.end() :]

    # Build date conditions with the downstream alias
    date_conds = (
        f'{alias}."{leaf_info.date_col}" >= \'{leaf_info.date_start}\'\n'
        f'      AND {alias}."{leaf_info.date_col}" < \'{leaf_info.date_end}\''
    )

    # Inject conditions into existing WHERE clause
    where_m = re.search(r"\bWHERE\b\s+", new_body, re.IGNORECASE)
    if where_m:
        # Insert date conditions at the start of WHERE
        insert_pos = where_m.end()
        new_body = (
            new_body[:insert_pos]
            + date_conds
            + "\n      AND "
            + new_body[insert_pos:]
        )
    else:
        new_body += f"\n    WHERE {date_conds}"

    return new_body


def _try_flatten(
    ctes: list[ParsedCTE],
    final_query: str,
    leaf_info: dict[str, _LeafInfo],
    deps: dict[str, frozenset[str]],
) -> str | None:
    """Flatten simple-scan leaf CTEs into downstream CTEs.

    Removes the CTE optimization fence so PostgreSQL can freely choose
    JOIN order and push small-table filters into the large table scan.

    Returns optimized SQL or None if no flattening was possible.
    """
    flattened: set[str] = set()
    new_ctes = list(ctes)

    for leaf_name, info in leaf_info.items():
        # Only flatten simple scans (no JOINs, no subqueries)
        if not info.is_simple_scan:
            continue

        leaf_used_in_downstream = False

        for i, cte in enumerate(new_ctes):
            if cte.name == leaf_name:
                continue
            # Skip if this CTE doesn't depend on the leaf
            if leaf_name not in deps.get(cte.name, frozenset()):
                continue

            new_body = _flatten_from_reference(leaf_name, info, cte.body)
            if new_body:
                new_ctes[i] = ParsedCTE(
                    name=cte.name, body=new_body, col_list=cte.col_list,
                )
                leaf_used_in_downstream = True

        if leaf_used_in_downstream:
            # Check if the leaf is also referenced in the final query
            leaf_in_final = bool(
                re.search(rf"\b{re.escape(leaf_name)}\b", final_query)
            )
            if not leaf_in_final:
                flattened.add(leaf_name)

    if not flattened:
        return None

    # Remove flattened leaf CTEs
    new_ctes = [c for c in new_ctes if c.name not in flattened]

    if not new_ctes:
        return None

    result = _rebuild_sql(new_ctes, final_query)

    logger.info(
        "Optimizer: flattened %d leaf CTEs (%s) into downstream CTEs",
        len(flattened),
        ", ".join(sorted(flattened)),
    )

    return result


# ---------------------------------------------------------------------------
# Merge optimization (fallback strategy)
# ---------------------------------------------------------------------------


def _try_merge(
    ctes: list[ParsedCTE],
    final_query: str,
    leaf_info: dict[str, _LeafInfo],
) -> str | None:
    """Merge duplicate table scans into a single scan with wrappers.

    Fallback when flattening is not applicable (leaf CTEs used in final query
    or have complex bodies).

    Returns optimized SQL or None.
    """
    # Group by fingerprint (identical bodies except for date values)
    groups: dict[str, list[tuple[str, _LeafInfo]]] = defaultdict(list)
    for name, info in leaf_info.items():
        groups[info.fingerprint].append((name, info))

    # Keep only groups with 2+ members (these are the duplicate scans)
    merge_groups = {k: v for k, v in groups.items() if len(v) >= 2}
    if not merge_groups:
        return None

    # Build replacement CTEs
    replaced: set[str] = set()
    inserts: dict[str, list[ParsedCTE]] = {}

    for _, members in merge_groups.items():
        first_name, first_info = members[0]

        merged_name = f"_{first_info.base_table.lower()}_merged"
        existing_names = {c.name for c in ctes}
        while merged_name in existing_names:
            merged_name += "_"

        starts = sorted(info.date_start for _, info in members)
        ends = sorted(info.date_end for _, info in members)
        combined_start = starts[0]
        combined_end = ends[-1]

        first_cte = next(c for c in ctes if c.name == first_name)
        merged_body = first_cte.body

        dm = _DATE_RANGE_RE.search(merged_body)
        if not dm:
            continue

        alias_prefix = f"{dm.group(1)}." if dm.group(1) else ""
        merged_body = (
            merged_body[: dm.start()]
            + f'{alias_prefix}"{first_info.date_col}" >= \'{combined_start}\''
            + f'\n      AND {alias_prefix}"{first_info.date_col}" < \'{combined_end}\''
            + merged_body[dm.end():]
        )

        date_col_quoted = f'"{first_info.date_col}"'
        if date_col_quoted not in first_info.select_clause:
            sm = _SELECT_RE.search(merged_body)
            if sm:
                if first_info.table_alias:
                    date_ref = f'{first_info.table_alias}."{first_info.date_col}"'
                else:
                    date_ref = date_col_quoted
                insert_pos = sm.end(2)
                merged_body = (
                    merged_body[:insert_pos]
                    + f", {date_ref}"
                    + merged_body[insert_pos:]
                )

        merged_cte = ParsedCTE(name=merged_name, body=merged_body)
        new_ctes_for_group: list[ParsedCTE] = [merged_cte]

        for name, info in members:
            wrapper_select = info.select_clause
            if info.table_alias:
                wrapper_select = re.sub(
                    rf"\b{re.escape(info.table_alias)}\s*\.\s*",
                    "",
                    wrapper_select,
                )
            distinct = "DISTINCT " if info.is_distinct else ""
            wrapper_body = (
                f"SELECT {distinct}{wrapper_select}\n"
                f"    FROM {merged_name}\n"
                f'    WHERE "{info.date_col}" >= \'{info.date_start}\'\n'
                f'      AND "{info.date_col}" < \'{info.date_end}\''
            )
            new_ctes_for_group.append(ParsedCTE(name=name, body=wrapper_body))
            replaced.add(name)

        inserts[first_name] = new_ctes_for_group

    if not replaced:
        return None

    new_ctes: list[ParsedCTE] = []
    for cte in ctes:
        if cte.name in inserts:
            new_ctes.extend(inserts[cte.name])
        elif cte.name not in replaced:
            new_ctes.append(cte)

    result = _rebuild_sql(new_ctes, final_query)

    logger.info(
        "Optimizer: merged %d CTEs scanning %s into single scan",
        len(replaced),
        ", ".join(sorted({leaf_info[n].base_table for n in replaced})),
    )

    return result


# ---------------------------------------------------------------------------
# SQL rebuilding
# ---------------------------------------------------------------------------


def _rebuild_sql(ctes: list[ParsedCTE], final_query: str) -> str:
    """Rebuild a full SQL statement from CTEs and final query."""
    cte_parts: list[str] = []
    for cte in ctes:
        if cte.col_list:
            col_str = ", ".join(f'"{c}"' for c in cte.col_list)
            cte_parts.append(f"{cte.name} ({col_str}) AS (\n    {cte.body}\n  )")
        else:
            cte_parts.append(f"{cte.name} AS (\n    {cte.body}\n  )")
    joined_ctes = ",\n  ".join(cte_parts)
    return f"WITH\n  {joined_ctes}\n{final_query}"


# ---------------------------------------------------------------------------
# Pre-execution of small leaf CTEs
# ---------------------------------------------------------------------------

# Tables known to be large (skip pre-execution for these)
_LARGE_TABLES = frozenset({
    "LVST", "OVST", "IPT", "OPT", "PRSC", "LVSTEXM",
    "PTDIAG", "OPDRUG", "IPDRUG", "OVSTEXM", "OVSTDRUG",
})

_PRE_EXEC_TIMEOUT_MS = 5000  # 5 seconds max per small CTE
_PRE_EXEC_MAX_ROWS = 500  # Only inline truly small results


def is_large_table_scan(body: str) -> bool:
    """Check if the CTE body scans a known large table."""
    m = _FROM_TABLE_RE.search(body)
    if m:
        return m.group(2).strip('"') in _LARGE_TABLES
    return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def optimize_query(sql: str) -> str | None:
    """Optimize SQL by removing CTE optimization fences.

    Strategy 1 (preferred): Flatten simple-scan leaf CTEs into downstream
    CTEs, allowing PostgreSQL to choose optimal JOIN order.

    Strategy 2 (fallback): Merge duplicate table scans with different date
    ranges into a single scan.

    Returns:
        Optimized SQL string, or None if no optimization was possible.
    """
    parsed = parse_ctes(sql)
    if not parsed:
        return None

    ctes, final_query = parsed
    if len(ctes) < 2:
        return None

    deps = analyze_dependencies(ctes)
    leaves = find_leaf_ctes(deps)
    if not leaves:
        return None

    # Analyze each leaf CTE
    leaf_info: dict[str, _LeafInfo] = {}
    for name in leaves:
        cte = next(c for c in ctes if c.name == name)
        info = _analyze_leaf(cte.body)
        if info:
            leaf_info[name] = info

    if not leaf_info:
        return None

    # Strategy 1: Flatten leaf CTEs into downstream CTEs
    result = _try_flatten(ctes, final_query, leaf_info, deps)
    if result:
        return result

    # Strategy 2: Merge duplicate date range scans
    merge_groups = defaultdict(list)
    for name, info in leaf_info.items():
        merge_groups[info.fingerprint].append((name, info))
    if any(len(v) >= 2 for v in merge_groups.values()):
        return _try_merge(ctes, final_query, leaf_info)

    return None
