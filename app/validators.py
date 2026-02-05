"""
Sanity check validators for query results.
"""

from __future__ import annotations

from typing import Any

from app.models import QueryResult, SanityCheckResult


def check_denominator(result: QueryResult, column_name: str = "count") -> SanityCheckResult:
    """
    Check that denominator/count values are positive.

    Args:
        result: Query result to check
        column_name: Name of the count/denominator column

    Returns:
        SanityCheckResult
    """
    try:
        col_idx = None
        for i, col in enumerate(result.columns):
            if col.lower() == column_name.lower():
                col_idx = i
                break

        if col_idx is None:
            return SanityCheckResult(
                check_name="denominator_check",
                passed=True,
                message=f"Column '{column_name}' not found, skipping check",
            )

        for row in result.rows:
            value = row[col_idx]
            if value is not None and value <= 0:
                return SanityCheckResult(
                    check_name="denominator_check",
                    passed=False,
                    message=f"Found non-positive value ({value}) in {column_name}",
                )

        return SanityCheckResult(
            check_name="denominator_check",
            passed=True,
            message="All denominator values are positive",
        )
    except Exception as e:
        return SanityCheckResult(
            check_name="denominator_check",
            passed=False,
            message=f"Check failed with error: {e}",
        )


def check_percent_range(
    result: QueryResult,
    column_name: str = "percent",
    min_val: float = 0.0,
    max_val: float = 100.0,
) -> SanityCheckResult:
    """
    Check that percentage values are within valid range.

    Args:
        result: Query result to check
        column_name: Name of the percentage column
        min_val: Minimum valid value
        max_val: Maximum valid value

    Returns:
        SanityCheckResult
    """
    try:
        col_idx = None
        for i, col in enumerate(result.columns):
            if column_name.lower() in col.lower():
                col_idx = i
                break

        if col_idx is None:
            return SanityCheckResult(
                check_name="percent_range_check",
                passed=True,
                message=f"No percentage column found, skipping check",
            )

        for row in result.rows:
            value = row[col_idx]
            if value is not None:
                if value < min_val or value > max_val:
                    return SanityCheckResult(
                        check_name="percent_range_check",
                        passed=False,
                        message=f"Percentage value ({value}) outside range [{min_val}, {max_val}]",
                    )

        return SanityCheckResult(
            check_name="percent_range_check",
            passed=True,
            message=f"All percentage values within [{min_val}, {max_val}]",
        )
    except Exception as e:
        return SanityCheckResult(
            check_name="percent_range_check",
            passed=False,
            message=f"Check failed with error: {e}",
        )


def check_non_empty(result: QueryResult) -> SanityCheckResult:
    """
    Check that result is not empty.

    Args:
        result: Query result to check

    Returns:
        SanityCheckResult
    """
    if result.row_count == 0:
        return SanityCheckResult(
            check_name="non_empty_check",
            passed=False,
            message="Query returned no results",
        )

    return SanityCheckResult(
        check_name="non_empty_check",
        passed=True,
        message=f"Query returned {result.row_count} rows",
    )


def check_reasonable_count(
    result: QueryResult,
    column_name: str = "count",
    min_expected: int = 0,
    max_expected: int | None = None,
) -> SanityCheckResult:
    """
    Check that count values are within reasonable bounds.

    Args:
        result: Query result to check
        column_name: Name of the count column
        min_expected: Minimum expected value
        max_expected: Maximum expected value (None = no upper limit)

    Returns:
        SanityCheckResult
    """
    try:
        col_idx = None
        for i, col in enumerate(result.columns):
            if column_name.lower() in col.lower():
                col_idx = i
                break

        if col_idx is None:
            return SanityCheckResult(
                check_name="reasonable_count_check",
                passed=True,
                message=f"No count column found, skipping check",
            )

        for row in result.rows:
            value = row[col_idx]
            if value is not None:
                if value < min_expected:
                    return SanityCheckResult(
                        check_name="reasonable_count_check",
                        passed=False,
                        message=f"Count ({value}) below minimum expected ({min_expected})",
                    )
                if max_expected is not None and value > max_expected:
                    return SanityCheckResult(
                        check_name="reasonable_count_check",
                        passed=False,
                        message=f"Count ({value}) above maximum expected ({max_expected})",
                    )

        return SanityCheckResult(
            check_name="reasonable_count_check",
            passed=True,
            message="Count values within reasonable bounds",
        )
    except Exception as e:
        return SanityCheckResult(
            check_name="reasonable_count_check",
            passed=False,
            message=f"Check failed with error: {e}",
        )


def run_sanity_checks(
    result: QueryResult,
    check_names: list[str] | None = None,
) -> list[SanityCheckResult]:
    """
    Run sanity checks on query result.

    Args:
        result: Query result to check
        check_names: Specific checks to run (None = all applicable)

    Returns:
        List of SanityCheckResult
    """
    results = []

    # Always check non-empty
    results.append(check_non_empty(result))

    # Check denominator if count column exists
    if check_names is None or "denominator" in str(check_names):
        results.append(check_denominator(result))

    # Check percent range if percent column exists
    if check_names is None or "percent" in str(check_names):
        results.append(check_percent_range(result))

    return results
