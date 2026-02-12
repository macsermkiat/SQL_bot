"""
Query complexity analysis for SQL queries.

Estimates query complexity based on structural features (joins, subqueries,
aggregations, etc.) and suggests appropriate timeouts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryComplexity:
    """Result of query complexity analysis."""

    level: str  # LOW, MEDIUM, HIGH, CRITICAL
    score: int  # Numeric score (0-100)
    estimated_seconds: float  # Estimated execution time
    suggested_timeout_ms: int  # Suggested statement_timeout
    factors: tuple[str, ...]  # What contributed to the score


def analyze_query_complexity(sql: str) -> QueryComplexity:
    """Analyze SQL query complexity based on structural features.

    Args:
        sql: SQL query string

    Returns:
        QueryComplexity with level, score, and suggested timeout
    """
    if not sql or not sql.strip():
        return QueryComplexity(
            level="LOW", score=0, estimated_seconds=0.1,
            suggested_timeout_ms=5000, factors=(),
        )

    upper = sql.upper()
    score = 0
    factors = []

    # Count JOINs
    join_count = len(re.findall(r'\bJOIN\b', upper))
    if join_count >= 4:
        score += 25
        factors.append(f"{join_count} JOINs")
    elif join_count >= 2:
        score += 10
        factors.append(f"{join_count} JOINs")

    # Count subqueries (SELECT inside parentheses)
    subquery_count = len(re.findall(r'\(\s*SELECT\b', upper))
    if subquery_count >= 2:
        score += 20
        factors.append(f"{subquery_count} subqueries")
    elif subquery_count >= 1:
        score += 10
        factors.append("subquery")

    # CTEs (WITH clauses)
    cte_count = len(re.findall(r'\bWITH\b', upper))
    if cte_count >= 1:
        score += 5
        factors.append("CTE")

    # Aggregation functions
    agg_funcs = re.findall(r'\b(COUNT|SUM|AVG|MIN|MAX|GROUP_CONCAT|STRING_AGG)\s*\(', upper)
    if len(agg_funcs) >= 3:
        score += 15
        factors.append(f"{len(agg_funcs)} aggregations")
    elif len(agg_funcs) >= 1:
        score += 5
        factors.append("aggregation")

    # GROUP BY
    if re.search(r'\bGROUP\s+BY\b', upper):
        score += 5
        factors.append("GROUP BY")

    # HAVING
    if re.search(r'\bHAVING\b', upper):
        score += 5
        factors.append("HAVING")

    # DISTINCT
    if re.search(r'\bDISTINCT\b', upper):
        score += 5
        factors.append("DISTINCT")

    # Window functions
    window_count = len(re.findall(r'\bOVER\s*\(', upper))
    if window_count >= 1:
        score += 15
        factors.append(f"{window_count} window function(s)")

    # UNION / INTERSECT / EXCEPT
    set_ops = len(re.findall(r'\b(UNION|INTERSECT|EXCEPT)\b', upper))
    if set_ops >= 1:
        score += 10 * set_ops
        factors.append(f"{set_ops} set operation(s)")

    # No date filter (potentially full table scan)
    has_date_filter = bool(re.search(
        r"(date|time|timestamp|vstdate|vstdttm|regdate|rxdate|orderdate)\s*(>|<|>=|<=|=|BETWEEN)",
        upper,
    ))
    if not has_date_filter:
        score += 10
        factors.append("no date filter")

    # LIKE with leading wildcard
    if re.search(r"LIKE\s+'%", upper):
        score += 5
        factors.append("leading wildcard LIKE")

    # CROSS JOIN
    if re.search(r'\bCROSS\s+JOIN\b', upper):
        score += 20
        factors.append("CROSS JOIN")

    # Determine level
    if score >= 60:
        level = "CRITICAL"
        estimated = 60.0
        timeout = 120000
    elif score >= 40:
        level = "HIGH"
        estimated = 30.0
        timeout = 60000
    elif score >= 20:
        level = "MEDIUM"
        estimated = 10.0
        timeout = 30000
    else:
        level = "LOW"
        estimated = 2.0
        timeout = 15000

    return QueryComplexity(
        level=level,
        score=min(score, 100),
        estimated_seconds=estimated,
        suggested_timeout_ms=timeout,
        factors=tuple(factors),
    )


def format_complexity_warning(complexity: QueryComplexity) -> str:
    """Format a user-facing warning for complex queries.

    Args:
        complexity: QueryComplexity result

    Returns:
        Warning string for the user
    """
    factors_str = ", ".join(complexity.factors) if complexity.factors else "multiple factors"
    return (
        f"Note: This is a {complexity.level.lower()}-complexity query "
        f"({factors_str}). It may take longer to execute."
    )
