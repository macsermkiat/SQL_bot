"""
SQL query optimizer for preventing timeout-causing patterns.

Primary optimization: Merge Duplicate Table Scans
When multiple CTEs scan the same large table with different date ranges,
merge them into a single scan with per-CTE date range filters.

Example - BEFORE (scans LVST twice -> timeout):
    WITH lvst_2024 AS (SELECT "labno", "hn" FROM LVST WHERE date >= '2024-01-01' AND date < '2025-01-01'),
         lvst_2025 AS (SELECT "labno", "hn" FROM LVST WHERE date >= '2025-01-01' AND date < '2026-01-01')

AFTER (single scan, ~2x faster):
    WITH _lvst_merged AS (SELECT "labno", "hn", "lvstdate" FROM LVST WHERE date >= '2024-01-01' AND date < '2026-01-01'),
         lvst_2024 AS (SELECT "labno", "hn" FROM _lvst_merged WHERE date >= '2024-01-01' AND date < '2025-01-01'),
         lvst_2025 AS (SELECT "labno", "hn" FROM _lvst_merged WHERE date >= '2025-01-01' AND date < '2026-01-01')
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
# Alias must not be a SQL keyword (WHERE, JOIN, INNER, LEFT, ON, etc.)
_SQL_KEYWORDS = frozenset({
    "WHERE", "JOIN", "INNER", "LEFT", "RIGHT", "OUTER", "CROSS", "FULL",
    "ON", "AND", "OR", "NOT", "ORDER", "GROUP", "HAVING", "LIMIT",
    "UNION", "EXCEPT", "INTERSECT", "AS", "SET", "INTO", "VALUES",
})
_FROM_TABLE_RE = re.compile(
    r'FROM\s+"KCMH_HIS"\s*\.\s*"(\w+)"(?:\s+(\w+))?',
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
    """Metadata extracted from a leaf CTE for merge analysis."""

    base_table: str  # e.g. "LVST"
    table_alias: str | None  # e.g. "lv" or None
    date_col: str  # e.g. "lvstdate"
    date_alias: str | None  # alias prefix on date col, e.g. "lv"
    date_start: str  # e.g. "2024-01-01"
    date_end: str  # e.g. "2025-01-01"
    select_clause: str  # e.g. '"labno", "hn"'
    is_distinct: bool
    fingerprint: str  # normalized body for grouping


def _analyze_leaf(body: str) -> _LeafInfo | None:
    """Extract merge-relevant metadata from a leaf CTE body.

    Returns None if the CTE is not a candidate for merging
    (no date range filter, no recognizable table, etc.).
    """
    table_m = _FROM_TABLE_RE.search(body)
    if not table_m:
        return None

    # Filter out SQL keywords captured as alias
    table_alias = table_m.group(2)
    if table_alias and table_alias.upper() in _SQL_KEYWORDS:
        table_alias = None

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

    return _LeafInfo(
        base_table=table_m.group(1),
        table_alias=table_alias,
        date_col=date_m.group(2),
        date_alias=date_m.group(1),  # alias prefix on date column
        date_start=date_m.group(3),
        date_end=date_m.group(6),
        select_clause=select_m.group(2).strip(),
        is_distinct=bool(select_m.group(1)),
        fingerprint=fp,
    )


# ---------------------------------------------------------------------------
# Core optimizer
# ---------------------------------------------------------------------------


def optimize_query(sql: str) -> str | None:
    """Optimize SQL by merging CTEs that scan the same table with different date ranges.

    When leaf CTEs (no inter-CTE dependencies) scan the same base table
    and differ only in their date range, this function:
    1. Creates a merged CTE that scans the table once with the combined range
    2. Replaces each original CTE with a lightweight filter on the merged CTE

    This prevents the most common timeout pattern: scanning huge tables
    (LVST, OVST, IPT) multiple times for different periods.

    Returns:
        Optimized SQL string, or None if no optimization was possible.
    """
    parsed = parse_ctes(sql)
    if not parsed:
        return None

    ctes, final_query = parsed
    if len(ctes) < 3:  # need at least 2 duplicate + 1 other CTE
        return None

    deps = analyze_dependencies(ctes)
    leaves = find_leaf_ctes(deps)
    if len(leaves) < 2:
        return None

    # Analyze each leaf CTE
    leaf_info: dict[str, _LeafInfo] = {}
    for name in leaves:
        cte = next(c for c in ctes if c.name == name)
        info = _analyze_leaf(cte.body)
        if info:
            leaf_info[name] = info

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
    # Map: first replaced CTE name -> [merged_cte, wrapper1, wrapper2, ...]
    inserts: dict[str, list[ParsedCTE]] = {}

    for _, members in merge_groups.items():
        first_name, first_info = members[0]

        # Generate unique merged CTE name
        merged_name = f"_{first_info.base_table.lower()}_merged"
        existing_names = {c.name for c in ctes}
        while merged_name in existing_names:
            merged_name += "_"

        # Combined date range: min(starts) to max(ends)
        starts = sorted(info.date_start for _, info in members)
        ends = sorted(info.date_end for _, info in members)
        combined_start = starts[0]
        combined_end = ends[-1]

        # Build merged CTE body from first member's body
        first_cte = next(c for c in ctes if c.name == first_name)
        merged_body = first_cte.body

        # Step 1: Replace the date range values with combined range
        dm = _DATE_RANGE_RE.search(merged_body)
        if not dm:
            continue

        alias_prefix = f"{dm.group(1)}." if dm.group(1) else ""
        merged_body = (
            merged_body[: dm.start()]
            + f'{alias_prefix}"{first_info.date_col}" >= \'{combined_start}\''
            + f'\n      AND {alias_prefix}"{first_info.date_col}" < \'{combined_end}\''
            + merged_body[dm.end() :]
        )

        # Step 2: Add date column to SELECT if not already present
        date_col_quoted = f'"{first_info.date_col}"'
        if date_col_quoted not in first_info.select_clause:
            sm = _SELECT_RE.search(merged_body)
            if sm:
                # Build the date column reference (with alias if original had one)
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

        # Build wrapper CTEs (one per original, filtering on date range)
        new_ctes_for_group: list[ParsedCTE] = [merged_cte]

        for name, info in members:
            # Strip table alias prefixes from select clause for the wrapper
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

    # Rebuild CTE list: insert merged+wrappers where the first replaced CTE was
    new_ctes: list[ParsedCTE] = []
    for cte in ctes:
        if cte.name in inserts:
            new_ctes.extend(inserts[cte.name])
        elif cte.name not in replaced:
            new_ctes.append(cte)

    # Rebuild SQL
    cte_parts: list[str] = []
    for cte in new_ctes:
        if cte.col_list:
            col_str = ", ".join(f'"{c}"' for c in cte.col_list)
            cte_parts.append(f"{cte.name} ({col_str}) AS (\n    {cte.body}\n  )")
        else:
            cte_parts.append(f"{cte.name} AS (\n    {cte.body}\n  )")

    optimized = f'WITH\n  {",\n  ".join(cte_parts)}\n{final_query}'

    logger.info(
        "Optimized: merged %d CTEs scanning %s into single scan",
        len(replaced),
        ", ".join(sorted({leaf_info[n].base_table for n in replaced})),
    )

    return optimized
