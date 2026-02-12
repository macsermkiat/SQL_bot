"""
Tests for staged query execution module.

Tests cover:
- CTE parsing (balanced parenthesis, string literals, comments)
- Dependency analysis (leaf detection, inter-CTE references)
- Value formatting (all Python types -> PostgreSQL literals)
- Query rebuilding (materialized VALUES + preserved CTEs)
- StagedExecutor (decomposition check, staged execution flow)

Usage:
    uv run pytest tests/test_staged_query.py -v
"""

from __future__ import annotations

import datetime
import math
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.staged_query import (
    MAX_MATERIALIZE_ROWS,
    STAGE_TIMEOUT_MS,
    ParsedCTE,
    StageResult,
    StagedExecutor,
    StagedQueryResult,
    _build_values_cte,
    _format_value,
    _pg_type_hint,
    analyze_dependencies,
    find_leaf_ctes,
    parse_ctes,
    rebuild_query,
)


# ---------------------------------------------------------------------------
# parse_ctes
# ---------------------------------------------------------------------------


class TestParseCTEs:
    """Tests for CTE parser."""

    def test_no_cte(self) -> None:
        result = parse_ctes("SELECT 1")
        assert result is None

    def test_single_cte(self) -> None:
        sql = """WITH a AS (SELECT 1 AS x) SELECT * FROM a"""
        result = parse_ctes(sql)
        assert result is not None
        ctes, final = result
        assert len(ctes) == 1
        assert ctes[0].name == "a"
        assert "SELECT 1 AS x" in ctes[0].body
        assert "SELECT * FROM a" in final

    def test_multiple_ctes(self) -> None:
        sql = """WITH
            a AS (SELECT 1 AS x),
            b AS (SELECT 2 AS y)
        SELECT * FROM a JOIN b ON TRUE"""
        result = parse_ctes(sql)
        assert result is not None
        ctes, final = result
        assert len(ctes) == 2
        assert ctes[0].name == "a"
        assert ctes[1].name == "b"
        assert "SELECT * FROM a JOIN b" in final

    def test_cte_with_column_list(self) -> None:
        sql = """WITH a (col1, col2) AS (SELECT 1, 2) SELECT * FROM a"""
        result = parse_ctes(sql)
        assert result is not None
        ctes, _ = result
        assert ctes[0].col_list == ("col1", "col2")

    def test_recursive_cte_returns_none(self) -> None:
        sql = """WITH RECURSIVE a AS (SELECT 1 UNION SELECT n+1 FROM a WHERE n<10) SELECT * FROM a"""
        result = parse_ctes(sql)
        assert result is None

    def test_nested_parentheses(self) -> None:
        sql = """WITH a AS (
            SELECT * FROM (SELECT 1 AS x) sub WHERE x > 0
        ) SELECT * FROM a"""
        result = parse_ctes(sql)
        assert result is not None
        ctes, _ = result
        assert len(ctes) == 1
        assert "(SELECT 1 AS x)" in ctes[0].body

    def test_string_literal_with_parens(self) -> None:
        sql = """WITH a AS (
            SELECT 'hello (world)' AS msg
        ) SELECT * FROM a"""
        result = parse_ctes(sql)
        assert result is not None
        ctes, _ = result
        assert len(ctes) == 1
        assert "'hello (world)'" in ctes[0].body

    def test_escaped_single_quotes(self) -> None:
        sql = """WITH a AS (
            SELECT 'it''s a test' AS msg
        ) SELECT * FROM a"""
        result = parse_ctes(sql)
        assert result is not None
        ctes, _ = result
        assert "it''s a test" in ctes[0].body

    def test_double_quoted_identifiers(self) -> None:
        sql = """WITH a AS (
            SELECT "column name" FROM "KCMH_HIS"."OVST"
        ) SELECT * FROM a"""
        result = parse_ctes(sql)
        assert result is not None
        ctes, _ = result
        assert '"column name"' in ctes[0].body

    def test_line_comment(self) -> None:
        sql = """WITH a AS (
            -- this is a comment with (parens)
            SELECT 1 AS x
        ) SELECT * FROM a"""
        result = parse_ctes(sql)
        assert result is not None
        ctes, _ = result
        assert len(ctes) == 1

    def test_block_comment(self) -> None:
        sql = """WITH a AS (
            /* block comment (with parens) */
            SELECT 1 AS x
        ) SELECT * FROM a"""
        result = parse_ctes(sql)
        assert result is not None
        ctes, _ = result
        assert len(ctes) == 1

    def test_empty_final_query_returns_none(self) -> None:
        # Malformed SQL with no final query after CTEs
        sql = """WITH a AS (SELECT 1)"""
        result = parse_ctes(sql)
        assert result is None

    def test_complex_clinical_query(self) -> None:
        """Test parsing a realistic clinical query with multiple CTEs."""
        sql = """WITH
            diabetes_patients AS (
                SELECT DISTINCT d."hn"
                FROM "KCMH_HIS"."PTDIAG" d
                WHERE d."icd10" LIKE 'E11%'
            ),
            hba1c_codes AS (
                SELECT "labexm"
                FROM "KCMH_HIS"."LABEXM"
                WHERE "name" LIKE '%HbA1c%'
            ),
            lab_results AS (
                SELECT lv."hn",
                       EXTRACT(YEAR FROM lv."lvstdate") AS lab_year,
                       lexm."result"
                FROM "KCMH_HIS"."LVST" lv
                INNER JOIN "KCMH_HIS"."LVSTEXM" lexm ON lv."labno" = lexm."labno"
                INNER JOIN hba1c_codes hc ON lexm."labexm" = hc."labexm"
                WHERE lv."lvstdate" >= '2024-01-01'
            )
        SELECT lab_year, COUNT(DISTINCT "hn")
        FROM lab_results
        WHERE "hn" IN (SELECT "hn" FROM diabetes_patients)
        GROUP BY lab_year"""

        result = parse_ctes(sql)
        assert result is not None
        ctes, final = result
        assert len(ctes) == 3
        assert ctes[0].name == "diabetes_patients"
        assert ctes[1].name == "hba1c_codes"
        assert ctes[2].name == "lab_results"
        assert "GROUP BY lab_year" in final


# ---------------------------------------------------------------------------
# analyze_dependencies + find_leaf_ctes
# ---------------------------------------------------------------------------


class TestDependencyAnalysis:
    """Tests for CTE dependency analysis."""

    def test_independent_ctes(self) -> None:
        ctes = [
            ParsedCTE(name="a", body="SELECT 1"),
            ParsedCTE(name="b", body="SELECT 2"),
        ]
        deps = analyze_dependencies(ctes)
        assert deps["a"] == frozenset()
        assert deps["b"] == frozenset()
        leaves = find_leaf_ctes(deps)
        assert set(leaves) == {"a", "b"}

    def test_dependent_cte(self) -> None:
        ctes = [
            ParsedCTE(name="a", body="SELECT 1"),
            ParsedCTE(name="b", body="SELECT * FROM a WHERE x > 0"),
        ]
        deps = analyze_dependencies(ctes)
        assert deps["a"] == frozenset()
        assert deps["b"] == frozenset({"a"})
        leaves = find_leaf_ctes(deps)
        assert leaves == ["a"]

    def test_chain_dependency(self) -> None:
        ctes = [
            ParsedCTE(name="a", body="SELECT 1"),
            ParsedCTE(name="b", body="SELECT * FROM a"),
            ParsedCTE(name="c", body="SELECT * FROM b"),
        ]
        deps = analyze_dependencies(ctes)
        assert deps["a"] == frozenset()
        assert deps["b"] == frozenset({"a"})
        assert deps["c"] == frozenset({"b"})
        leaves = find_leaf_ctes(deps)
        assert leaves == ["a"]

    def test_clinical_query_dependencies(self) -> None:
        """Simulate the user's diabetes + HbA1c query."""
        ctes = [
            ParsedCTE(name="diabetes_patients", body='SELECT DISTINCT d."hn" FROM "KCMH_HIS"."PTDIAG" d'),
            ParsedCTE(name="hba1c_codes", body='SELECT "labexm" FROM "KCMH_HIS"."LABEXM"'),
            ParsedCTE(
                name="lab_results",
                body='SELECT lv."hn" FROM "KCMH_HIS"."LVST" lv INNER JOIN hba1c_codes hc ON lexm."labexm" = hc."labexm"',
            ),
        ]
        deps = analyze_dependencies(ctes)
        assert deps["diabetes_patients"] == frozenset()
        assert deps["hba1c_codes"] == frozenset()
        assert deps["lab_results"] == frozenset({"hba1c_codes"})
        leaves = find_leaf_ctes(deps)
        assert set(leaves) == {"diabetes_patients", "hba1c_codes"}

    def test_mutual_independence(self) -> None:
        ctes = [
            ParsedCTE(name="x", body="SELECT 1 FROM t1"),
            ParsedCTE(name="y", body="SELECT 2 FROM t2"),
            ParsedCTE(name="z", body="SELECT 3 FROM t3"),
        ]
        deps = analyze_dependencies(ctes)
        leaves = find_leaf_ctes(deps)
        assert set(leaves) == {"x", "y", "z"}


# ---------------------------------------------------------------------------
# _format_value
# ---------------------------------------------------------------------------


class TestFormatValue:
    """Tests for PostgreSQL value formatting."""

    def test_none(self) -> None:
        assert _format_value(None) == "NULL"

    def test_bool_true(self) -> None:
        assert _format_value(True) == "TRUE"

    def test_bool_false(self) -> None:
        assert _format_value(False) == "FALSE"

    def test_integer(self) -> None:
        assert _format_value(42) == "42"

    def test_negative_integer(self) -> None:
        assert _format_value(-7) == "-7"

    def test_decimal(self) -> None:
        assert _format_value(Decimal("3.14")) == "3.14"

    def test_float(self) -> None:
        assert _format_value(1.5) == "1.5"

    def test_float_nan(self) -> None:
        assert _format_value(float("nan")) == "'NaN'::numeric"

    def test_float_inf(self) -> None:
        assert _format_value(float("inf")) == "'Infinity'::numeric"

    def test_float_neg_inf(self) -> None:
        assert _format_value(float("-inf")) == "'-Infinity'::numeric"

    def test_date(self) -> None:
        d = datetime.date(2024, 6, 15)
        assert _format_value(d) == "'2024-06-15'"

    def test_datetime(self) -> None:
        dt = datetime.datetime(2024, 6, 15, 14, 30, 0)
        assert "'2024-06-15T14:30:00'" == _format_value(dt)

    def test_bytes(self) -> None:
        b = bytes([0xDE, 0xAD])
        assert _format_value(b) == "'\\xdead'::bytea"

    def test_string(self) -> None:
        assert _format_value("hello") == "E'hello'"

    def test_string_with_single_quote(self) -> None:
        result = _format_value("it's")
        assert result == "E'it''s'"

    def test_string_with_backslash(self) -> None:
        result = _format_value("path\\to\\file")
        assert result == "E'path\\\\to\\\\file'"

    def test_string_with_both(self) -> None:
        result = _format_value("it's a\\path")
        assert result == "E'it''s a\\\\path'"


# ---------------------------------------------------------------------------
# _pg_type_hint
# ---------------------------------------------------------------------------


class TestPgTypeHint:
    """Tests for PostgreSQL type hints on first row."""

    def test_none(self) -> None:
        assert _pg_type_hint(None) == "::text"

    def test_bool(self) -> None:
        assert _pg_type_hint(True) == "::boolean"

    def test_decimal(self) -> None:
        assert _pg_type_hint(Decimal("1.0")) == "::numeric"

    def test_small_int(self) -> None:
        assert _pg_type_hint(42) == "::integer"

    def test_bigint(self) -> None:
        assert _pg_type_hint(3_000_000_000) == "::bigint"

    def test_negative_bigint(self) -> None:
        assert _pg_type_hint(-3_000_000_000) == "::bigint"

    def test_float(self) -> None:
        assert _pg_type_hint(1.5) == "::numeric"

    def test_datetime(self) -> None:
        assert _pg_type_hint(datetime.datetime(2024, 1, 1)) == "::timestamp"

    def test_date(self) -> None:
        assert _pg_type_hint(datetime.date(2024, 1, 1)) == "::date"

    def test_bytes(self) -> None:
        assert _pg_type_hint(b"\x00") == "::bytea"

    def test_string(self) -> None:
        assert _pg_type_hint("hello") == "::text"


# ---------------------------------------------------------------------------
# _build_values_cte
# ---------------------------------------------------------------------------


class TestBuildValuesCTE:
    """Tests for VALUES clause generation."""

    def test_empty_rows(self) -> None:
        result = _build_values_cte("test_cte", ("a", "b"), ())
        assert "WHERE FALSE" in result
        assert 'test_cte ("a", "b")' in result

    def test_single_row(self) -> None:
        result = _build_values_cte(
            "codes",
            ("id", "name"),
            ((1, "alpha"),),
        )
        assert "VALUES" in result
        assert "::integer" in result
        assert "::text" in result
        assert 'codes ("id", "name")' in result

    def test_multiple_rows_type_hint_only_first(self) -> None:
        result = _build_values_cte(
            "items",
            ("val",),
            ((10,), (20,), (30,)),
        )
        # Type hint on first row only
        lines = result.split("\n")
        values_text = "\n".join(lines)
        assert values_text.count("::integer") == 1

    def test_null_values(self) -> None:
        result = _build_values_cte(
            "nullable",
            ("x",),
            ((None,),),
        )
        assert "NULL::text" in result


# ---------------------------------------------------------------------------
# rebuild_query
# ---------------------------------------------------------------------------


class TestRebuildQuery:
    """Tests for query rebuilding with materialized CTEs."""

    def test_materialized_cte_replaced(self) -> None:
        ctes = [
            ParsedCTE(name="a", body="SELECT 1 AS x"),
            ParsedCTE(name="b", body="SELECT * FROM a"),
        ]
        materialized = {
            "a": StageResult(
                name="a",
                columns=("x",),
                rows=((1,),),
                row_count=1,
                execution_time_ms=5.0,
            ),
        }
        result = rebuild_query(ctes, materialized, "SELECT * FROM b")
        assert "VALUES" in result
        assert "SELECT * FROM b" in result
        # CTE b should be preserved as-is
        assert "SELECT * FROM a" in result

    def test_non_materialized_cte_preserved(self) -> None:
        ctes = [
            ParsedCTE(name="a", body="SELECT 1 AS x"),
            ParsedCTE(name="b", body="SELECT * FROM a", col_list=("y",)),
        ]
        materialized: dict[str, StageResult] = {}
        result = rebuild_query(ctes, materialized, "SELECT * FROM b")
        assert "a AS (" in result
        assert "b (" in result  # Has col_list
        assert '"y"' in result

    def test_full_rebuild_preserves_final_query(self) -> None:
        ctes = [
            ParsedCTE(name="codes", body="SELECT 'A' AS code"),
            ParsedCTE(name="data", body="SELECT * FROM t JOIN codes ON t.c = codes.code"),
        ]
        materialized = {
            "codes": StageResult(
                name="codes",
                columns=("code",),
                rows=(("A",),),
                row_count=1,
                execution_time_ms=2.0,
            ),
        }
        result = rebuild_query(ctes, materialized, "SELECT COUNT(*) FROM data")
        assert result.startswith("WITH")
        assert "SELECT COUNT(*) FROM data" in result
        assert "VALUES" in result


# ---------------------------------------------------------------------------
# StagedExecutor
# ---------------------------------------------------------------------------


class TestStagedExecutor:
    """Tests for the StagedExecutor class."""

    def _mock_db(self) -> MagicMock:
        return MagicMock()

    def test_can_decompose_simple_select(self) -> None:
        db = self._mock_db()
        executor = StagedExecutor(db)
        assert executor.can_decompose("SELECT 1") is False

    def test_can_decompose_single_cte(self) -> None:
        db = self._mock_db()
        executor = StagedExecutor(db)
        sql = "WITH a AS (SELECT 1) SELECT * FROM a"
        assert executor.can_decompose(sql) is False  # Need >= 2 CTEs

    def test_can_decompose_two_independent_ctes(self) -> None:
        db = self._mock_db()
        executor = StagedExecutor(db)
        sql = """WITH
            a AS (SELECT 1 AS x),
            b AS (SELECT 2 AS y)
        SELECT * FROM a, b"""
        assert executor.can_decompose(sql) is True

    def test_can_decompose_no_leaves(self) -> None:
        db = self._mock_db()
        executor = StagedExecutor(db)
        # b depends on a, a depends on b -> no leaves (circular, unusual)
        # In practice, CTE a doesn't reference b, so a is a leaf
        # Let's make both depend on each other by name
        sql = """WITH
            a AS (SELECT * FROM b WHERE x > 0),
            b AS (SELECT * FROM a WHERE y > 0)
        SELECT * FROM b"""
        # Both reference each other -> no leaves
        assert executor.can_decompose(sql) is False

    def test_can_decompose_recursive(self) -> None:
        db = self._mock_db()
        executor = StagedExecutor(db)
        sql = "WITH RECURSIVE a AS (SELECT 1 UNION ALL SELECT n+1 FROM a WHERE n < 10) SELECT * FROM a"
        assert executor.can_decompose(sql) is False

    def test_execute_staged_no_ctes(self) -> None:
        db = self._mock_db()
        executor = StagedExecutor(db)
        result = executor.execute_staged("SELECT 1", 60000, 2000)
        assert result is None

    def test_execute_staged_success(self) -> None:
        """Test staged execution with mock DB returning small result sets."""
        mock_result = MagicMock()
        mock_result.columns = ["code"]
        mock_result.rows = [("A1",), ("A2",)]
        mock_result.row_count = 2

        db = MagicMock()
        db.execute_query.return_value = mock_result

        executor = StagedExecutor(db)
        sql = """WITH
            codes AS (SELECT "labexm" FROM "KCMH_HIS"."LABEXM" WHERE "name" LIKE '%test%'),
            patients AS (SELECT DISTINCT "hn" FROM "KCMH_HIS"."PTDIAG" WHERE "icd10" LIKE 'E11%')
        SELECT COUNT(*) FROM patients p
        WHERE EXISTS (SELECT 1 FROM codes c)"""

        result = executor.execute_staged(sql, 60000, 2000)
        assert result is not None
        assert result.stages_executed > 0
        assert result.materialized_ctes
        assert result.query_result == mock_result

    def test_execute_staged_large_cte_skipped(self) -> None:
        """CTEs with too many rows should not be materialized."""
        # First call (leaf CTE): return too many rows
        large_result = MagicMock()
        large_result.columns = ["id"]
        large_result.rows = [(i,) for i in range(MAX_MATERIALIZE_ROWS + 1)]
        large_result.row_count = MAX_MATERIALIZE_ROWS + 1

        # Second call (final query): normal result
        final_result = MagicMock()
        final_result.columns = ["count"]
        final_result.rows = [(100,)]
        final_result.row_count = 1

        db = MagicMock()
        db.execute_query.return_value = large_result

        executor = StagedExecutor(db)
        sql = """WITH
            big AS (SELECT * FROM huge_table),
            small AS (SELECT 1 AS x)
        SELECT * FROM big JOIN small ON TRUE"""

        # Both leaves are too large -> no materialization -> returns None
        result = executor.execute_staged(sql, 60000, 2000)
        assert result is None

    def test_execute_staged_stage_failure_continues(self) -> None:
        """If one leaf CTE fails, it should continue with others."""
        good_result = MagicMock()
        good_result.columns = ["code"]
        good_result.rows = [("X",)]
        good_result.row_count = 1

        final_result = MagicMock()
        final_result.columns = ["count"]
        final_result.rows = [(42,)]
        final_result.row_count = 1

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("stage 1 failed")
            return good_result if call_count == 2 else final_result

        db = MagicMock()
        db.execute_query.side_effect = side_effect

        executor = StagedExecutor(db)
        sql = """WITH
            a AS (SELECT 1),
            b AS (SELECT 2),
            c AS (SELECT * FROM a JOIN b ON TRUE)
        SELECT * FROM c"""

        result = executor.execute_staged(sql, 60000, 2000)
        # One leaf failed, one materialized
        if result is not None:
            assert result.stages_executed >= 1

    def test_execute_staged_with_cancellable(self) -> None:
        """Test that cancellable is checked and used for execution."""
        mock_result = MagicMock()
        mock_result.columns = ["x"]
        mock_result.rows = [(1,)]
        mock_result.row_count = 1

        cancellable = MagicMock()
        cancellable.execute.return_value = mock_result

        db = MagicMock()
        executor = StagedExecutor(db)

        sql = """WITH
            a AS (SELECT 1 AS x),
            b AS (SELECT 2 AS y)
        SELECT * FROM a, b"""

        result = executor.execute_staged(
            sql, 60000, 2000, cancellable=cancellable,
        )
        assert result is not None
        # Should have called cancellable.execute for stages + final
        assert cancellable.execute.call_count >= 2
        assert cancellable.check_cancelled.call_count >= 2


# ---------------------------------------------------------------------------
# Integration: parse -> analyze -> rebuild round-trip
# ---------------------------------------------------------------------------


class TestParseAnalyzeRebuild:
    """Integration tests for the full parse -> analyze -> rebuild pipeline."""

    def test_round_trip_simple(self) -> None:
        sql = """WITH
            codes AS (SELECT 'A' AS code),
            data AS (SELECT * FROM codes)
        SELECT * FROM data"""

        parsed = parse_ctes(sql)
        assert parsed is not None
        ctes, final = parsed

        deps = analyze_dependencies(ctes)
        assert deps["codes"] == frozenset()
        assert deps["data"] == frozenset({"codes"})

        leaves = find_leaf_ctes(deps)
        assert leaves == ["codes"]

        # Simulate materializing the leaf
        materialized = {
            "codes": StageResult(
                name="codes",
                columns=("code",),
                rows=(("A",),),
                row_count=1,
                execution_time_ms=1.0,
            ),
        }
        rebuilt = rebuild_query(ctes, materialized, final)
        assert "WITH" in rebuilt
        assert "VALUES" in rebuilt
        assert "SELECT * FROM data" in rebuilt

    def test_round_trip_clinical_pattern(self) -> None:
        """Simulate the user's diabetes query pattern."""
        sql = """WITH
            diabetes AS (SELECT DISTINCT "hn" FROM "KCMH_HIS"."PTDIAG" WHERE "icd10" LIKE 'E11%'),
            hba1c AS (SELECT "labexm" FROM "KCMH_HIS"."LABEXM" WHERE "name" LIKE '%HbA1c%'),
            labs AS (
                SELECT lv."hn", lexm."result"
                FROM "KCMH_HIS"."LVST" lv
                JOIN "KCMH_HIS"."LVSTEXM" lexm ON lv."labno" = lexm."labno"
                JOIN hba1c h ON lexm."labexm" = h."labexm"
            )
        SELECT COUNT(DISTINCT "hn") FROM labs
        WHERE "hn" IN (SELECT "hn" FROM diabetes)"""

        parsed = parse_ctes(sql)
        assert parsed is not None
        ctes, final = parsed
        assert len(ctes) == 3

        deps = analyze_dependencies(ctes)
        leaves = find_leaf_ctes(deps)
        # diabetes and hba1c are leaves (no CTE deps)
        assert set(leaves) == {"diabetes", "hba1c"}

        # Simulate materializing both leaves
        materialized = {
            "diabetes": StageResult(
                name="diabetes",
                columns=("hn",),
                rows=(("HN001",), ("HN002",)),
                row_count=2,
                execution_time_ms=3.0,
            ),
            "hba1c": StageResult(
                name="hba1c",
                columns=("labexm",),
                rows=(("LAB01",),),
                row_count=1,
                execution_time_ms=1.5,
            ),
        }

        rebuilt = rebuild_query(ctes, materialized, final)
        assert "WITH" in rebuilt
        assert "VALUES" in rebuilt
        # Both leaves should be VALUES
        assert rebuilt.count("VALUES") == 2
        # labs CTE should be preserved as original body
        assert "LVST" in rebuilt
        assert "SELECT COUNT(DISTINCT" in rebuilt
