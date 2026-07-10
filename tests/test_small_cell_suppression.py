"""Tests for post-execution small-cell suppression."""

from app.chat import _suppress_small_cells


def test_suppresses_rows_below_five():
    rows = [["A", 4], ["B", 5], ["C", 12]]

    filtered, suppressed = _suppress_small_cells(rows, ["ward", "n"], ["n"])

    assert filtered == [["B", 5], ["C", 12]]
    assert suppressed == 1


def test_suppresses_when_any_count_is_below_five():
    rows = [["A", 8, 3], ["B", 6, 7]]

    filtered, suppressed = _suppress_small_cells(
        rows, ["ward", "patients", "visits"], ["patients", "visits"]
    )

    assert filtered == [["B", 6, 7]]
    assert suppressed == 1


def test_leaves_rows_unchanged_without_matching_count_column():
    rows = [["A", 1]]

    filtered, suppressed = _suppress_small_cells(rows, ["ward", "total"], ["n"])

    assert filtered is rows
    assert suppressed == 0


def test_non_numeric_count_value_is_not_suppressed():
    rows = [["A", None], ["B", "3"]]

    filtered, suppressed = _suppress_small_cells(rows, ["ward", "n"], ["n"])

    assert filtered == rows
    assert suppressed == 0
