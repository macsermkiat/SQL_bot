"""
Tests for SQL query optimizer (duplicate table scan merger).

Usage:
    uv run pytest tests/test_sql_optimizer.py -v
"""

from __future__ import annotations

import pytest

from app.sql_optimizer import _analyze_leaf, optimize_query


# ---------------------------------------------------------------------------
# _analyze_leaf
# ---------------------------------------------------------------------------


class TestAnalyzeLeaf:
    """Tests for leaf CTE metadata extraction."""

    def test_simple_leaf(self) -> None:
        body = """SELECT "labno", "hn"
    FROM "KCMH_HIS"."LVST"
    WHERE "lvstdate" >= '2024-01-01'
      AND "lvstdate" < '2025-01-01'"""
        info = _analyze_leaf(body)
        assert info is not None
        assert info.base_table == "LVST"
        assert info.date_col == "lvstdate"
        assert info.date_start == "2024-01-01"
        assert info.date_end == "2025-01-01"
        assert '"labno"' in info.select_clause
        assert '"hn"' in info.select_clause
        assert info.is_distinct is False
        assert info.table_alias is None

    def test_leaf_with_alias(self) -> None:
        body = """SELECT lv."labno", lv."hn"
    FROM "KCMH_HIS"."LVST" lv
    WHERE lv."lvstdate" >= '2024-01-01'
      AND lv."lvstdate" < '2025-01-01'"""
        info = _analyze_leaf(body)
        assert info is not None
        assert info.base_table == "LVST"
        assert info.table_alias == "lv"
        assert info.date_alias == "lv"

    def test_leaf_with_distinct(self) -> None:
        body = """SELECT DISTINCT "hn"
    FROM "KCMH_HIS"."PTDIAG"
    WHERE "vstdate" >= '2024-01-01'
      AND "vstdate" < '2025-01-01'"""
        info = _analyze_leaf(body)
        assert info is not None
        assert info.is_distinct is True

    def test_no_date_range(self) -> None:
        body = """SELECT "labexm"
    FROM "KCMH_HIS"."LABEXM"
    WHERE "name" ILIKE '%HbA1c%'"""
        info = _analyze_leaf(body)
        assert info is None

    def test_no_from_table(self) -> None:
        body = """SELECT 1 AS x"""
        info = _analyze_leaf(body)
        assert info is None

    def test_fingerprint_matches_for_same_structure(self) -> None:
        body_2024 = """SELECT "labno", "hn"
    FROM "KCMH_HIS"."LVST"
    WHERE "lvstdate" >= '2024-01-01'
      AND "lvstdate" < '2025-01-01'"""
        body_2025 = """SELECT "labno", "hn"
    FROM "KCMH_HIS"."LVST"
    WHERE "lvstdate" >= '2025-01-01'
      AND "lvstdate" < '2026-01-01'"""
        info1 = _analyze_leaf(body_2024)
        info2 = _analyze_leaf(body_2025)
        assert info1 is not None
        assert info2 is not None
        assert info1.fingerprint == info2.fingerprint

    def test_fingerprint_differs_for_different_tables(self) -> None:
        body_lvst = """SELECT "labno" FROM "KCMH_HIS"."LVST"
    WHERE "lvstdate" >= '2024-01-01' AND "lvstdate" < '2025-01-01'"""
        body_ovst = """SELECT "labno" FROM "KCMH_HIS"."OVST"
    WHERE "vstdate" >= '2024-01-01' AND "vstdate" < '2025-01-01'"""
        info1 = _analyze_leaf(body_lvst)
        info2 = _analyze_leaf(body_ovst)
        assert info1 is not None
        assert info2 is not None
        assert info1.fingerprint != info2.fingerprint


# ---------------------------------------------------------------------------
# optimize_query - no optimization cases
# ---------------------------------------------------------------------------


class TestOptimizeNoOp:
    """Cases where the optimizer should return None (no optimization)."""

    def test_no_ctes(self) -> None:
        assert optimize_query("SELECT 1") is None

    def test_single_cte(self) -> None:
        sql = "WITH a AS (SELECT 1) SELECT * FROM a"
        assert optimize_query(sql) is None

    def test_two_ctes_different_tables(self) -> None:
        sql = """WITH
            a AS (SELECT "hn" FROM "KCMH_HIS"."LVST" WHERE "lvstdate" >= '2024-01-01' AND "lvstdate" < '2025-01-01'),
            b AS (SELECT "vn" FROM "KCMH_HIS"."OVST" WHERE "vstdate" >= '2024-01-01' AND "vstdate" < '2025-01-01'),
            c AS (SELECT * FROM a JOIN b ON TRUE)
        SELECT * FROM c"""
        assert optimize_query(sql) is None

    def test_two_ctes_no_date_filter(self) -> None:
        sql = """WITH
            a AS (SELECT "labexm" FROM "KCMH_HIS"."LABEXM" WHERE "name" LIKE '%test%'),
            b AS (SELECT "icd10" FROM "KCMH_HIS"."ICD10" WHERE "icd10" LIKE 'E11%'),
            c AS (SELECT * FROM a, b)
        SELECT * FROM c"""
        assert optimize_query(sql) is None

    def test_recursive_cte(self) -> None:
        sql = "WITH RECURSIVE a AS (SELECT 1 UNION ALL SELECT n+1 FROM a WHERE n < 10) SELECT * FROM a"
        assert optimize_query(sql) is None


# ---------------------------------------------------------------------------
# optimize_query - successful optimization cases
# ---------------------------------------------------------------------------


class TestOptimizeMerge:
    """Cases where duplicate table scans should be merged."""

    def test_basic_two_year_merge(self) -> None:
        sql = """WITH
            lvst_2024 AS (
                SELECT "labno", "hn"
                FROM "KCMH_HIS"."LVST"
                WHERE "lvstdate" >= '2024-01-01'
                  AND "lvstdate" < '2025-01-01'
            ),
            lvst_2025 AS (
                SELECT "labno", "hn"
                FROM "KCMH_HIS"."LVST"
                WHERE "lvstdate" >= '2025-01-01'
                  AND "lvstdate" < '2026-01-01'
            ),
            combined AS (
                SELECT * FROM lvst_2024
                UNION ALL
                SELECT * FROM lvst_2025
            )
        SELECT COUNT(*) FROM combined"""

        result = optimize_query(sql)
        assert result is not None

        # Should have a merged CTE
        assert "_lvst_merged" in result

        # Combined date range should cover both years
        assert "'2024-01-01'" in result
        assert "'2026-01-01'" in result

        # Original CTE names should still exist (as wrappers)
        assert "lvst_2024" in result
        assert "lvst_2025" in result

        # Date column should be in merged CTE for filtering
        assert '"lvstdate"' in result

        # Final query should be preserved
        assert "SELECT COUNT(*) FROM combined" in result

    def test_users_exact_query(self) -> None:
        """Test the exact query pattern causing the user's timeout."""
        sql = """WITH diabetes_patients AS (
    SELECT DISTINCT "hn"
    FROM "KCMH_HIS"."PTDIAG"
    WHERE "icd10" LIKE 'E11%'
),
hba1c_labexm AS (
    SELECT "labexm"
    FROM "KCMH_HIS"."LABEXM"
    WHERE ("name" ILIKE '%HbA1c%' OR "name" ILIKE '%A1C%' OR "name" ILIKE '%Glycated%')
),
lvst_2024 AS (
    SELECT "labno", "hn"
    FROM "KCMH_HIS"."LVST"
    WHERE "lvstdate" >= '2024-01-01'
      AND "lvstdate" < '2025-01-01'
),
lvst_2025 AS (
    SELECT "labno", "hn"
    FROM "KCMH_HIS"."LVST"
    WHERE "lvstdate" >= '2025-01-01'
      AND "lvstdate" < '2026-01-01'
),
hba1c_2024 AS (
    SELECT DISTINCT l24."hn"
    FROM lvst_2024 l24
    INNER JOIN "KCMH_HIS"."LVSTEXM" lexm ON l24."labno" = lexm."labno"
    INNER JOIN hba1c_labexm hl ON lexm."labexm" = hl."labexm"
    WHERE lexm."result" IS NOT NULL
      AND CASE WHEN lexm."result" ~ '^[0-9]+(\\.)?\\ [0-9]*$'
                THEN CAST(lexm."result" AS NUMERIC)
                ELSE NULL END < 7.0
),
hba1c_2025 AS (
    SELECT DISTINCT l25."hn"
    FROM lvst_2025 l25
    INNER JOIN "KCMH_HIS"."LVSTEXM" lexm ON l25."labno" = lexm."labno"
    INNER JOIN hba1c_labexm hl ON lexm."labexm" = hl."labexm"
    WHERE lexm."result" IS NOT NULL
      AND CASE WHEN lexm."result" ~ '^[0-9]+(\\.)?\\ [0-9]*$'
                THEN CAST(lexm."result" AS NUMERIC)
                ELSE NULL END >= 8.0
)
SELECT COUNT(*) AS patient_count
FROM diabetes_patients dp
WHERE EXISTS (SELECT 1 FROM hba1c_2024 h24 WHERE h24."hn" = dp."hn")
  AND EXISTS (SELECT 1 FROM hba1c_2025 h25 WHERE h25."hn" = dp."hn")"""

        result = optimize_query(sql)
        assert result is not None

        # Should merge lvst_2024 and lvst_2025 into _lvst_merged
        assert "_lvst_merged" in result

        # Combined range: 2024-01-01 to 2026-01-01
        assert "'2024-01-01'" in result
        assert "'2026-01-01'" in result

        # Wrapper CTEs still exist
        assert "lvst_2024 AS" in result
        assert "lvst_2025 AS" in result

        # Wrappers reference merged CTE
        assert "FROM _lvst_merged" in result

        # Non-duplicate CTEs preserved unchanged
        assert "diabetes_patients AS" in result
        assert "hba1c_labexm AS" in result
        assert "hba1c_2024 AS" in result
        assert "hba1c_2025 AS" in result

        # Final query preserved
        assert "SELECT COUNT(*) AS patient_count" in result
        assert "FROM diabetes_patients dp" in result

    def test_three_year_merge(self) -> None:
        sql = """WITH
            y23 AS (SELECT "vn" FROM "KCMH_HIS"."OVST" WHERE "vstdate" >= '2023-01-01' AND "vstdate" < '2024-01-01'),
            y24 AS (SELECT "vn" FROM "KCMH_HIS"."OVST" WHERE "vstdate" >= '2024-01-01' AND "vstdate" < '2025-01-01'),
            y25 AS (SELECT "vn" FROM "KCMH_HIS"."OVST" WHERE "vstdate" >= '2025-01-01' AND "vstdate" < '2026-01-01'),
            agg AS (SELECT COUNT(*) FROM y23 UNION ALL SELECT COUNT(*) FROM y24 UNION ALL SELECT COUNT(*) FROM y25)
        SELECT * FROM agg"""

        result = optimize_query(sql)
        assert result is not None
        assert "_ovst_merged" in result
        # Combined range: 2023-01-01 to 2026-01-01
        assert "'2023-01-01'" in result
        assert "'2026-01-01'" in result

    def test_preserves_non_duplicate_ctes(self) -> None:
        sql = """WITH
            codes AS (SELECT "labexm" FROM "KCMH_HIS"."LABEXM" WHERE "name" LIKE '%test%'),
            lvst_2024 AS (SELECT "labno", "hn" FROM "KCMH_HIS"."LVST" WHERE "lvstdate" >= '2024-01-01' AND "lvstdate" < '2025-01-01'),
            lvst_2025 AS (SELECT "labno", "hn" FROM "KCMH_HIS"."LVST" WHERE "lvstdate" >= '2025-01-01' AND "lvstdate" < '2026-01-01'),
            data AS (SELECT * FROM lvst_2024 UNION ALL SELECT * FROM lvst_2025)
        SELECT * FROM data"""

        result = optimize_query(sql)
        assert result is not None
        # codes CTE should be preserved as-is
        assert "codes AS" in result
        assert "LABEXM" in result
        # data CTE preserved
        assert "data AS" in result


class TestOptimizeOutputValidity:
    """Verify the optimized SQL is structurally valid."""

    def test_starts_with_WITH(self) -> None:
        sql = """WITH
            a AS (SELECT "hn" FROM "KCMH_HIS"."LVST" WHERE "lvstdate" >= '2024-01-01' AND "lvstdate" < '2025-01-01'),
            b AS (SELECT "hn" FROM "KCMH_HIS"."LVST" WHERE "lvstdate" >= '2025-01-01' AND "lvstdate" < '2026-01-01'),
            c AS (SELECT * FROM a UNION ALL SELECT * FROM b)
        SELECT COUNT(*) FROM c"""

        result = optimize_query(sql)
        assert result is not None
        assert result.strip().startswith("WITH")

    def test_wrapper_has_correct_date_filter(self) -> None:
        sql = """WITH
            a AS (SELECT "hn" FROM "KCMH_HIS"."LVST" WHERE "lvstdate" >= '2024-01-01' AND "lvstdate" < '2025-01-01'),
            b AS (SELECT "hn" FROM "KCMH_HIS"."LVST" WHERE "lvstdate" >= '2025-01-01' AND "lvstdate" < '2026-01-01'),
            c AS (SELECT * FROM a UNION ALL SELECT * FROM b)
        SELECT COUNT(*) FROM c"""

        result = optimize_query(sql)
        assert result is not None
        # Wrapper 'a' should filter for 2024
        # Wrapper 'b' should filter for 2025
        # Check that original date ranges appear in wrappers
        lines = result.split("\n")
        # Find wrapper CTE 'a'
        found_a_wrapper = False
        for i, line in enumerate(lines):
            if "a AS" in line and "_lvst_merged" not in line:
                # Look ahead for the date filter
                context = "\n".join(lines[i : i + 5])
                if "FROM _lvst_merged" in context:
                    assert "'2024-01-01'" in context
                    assert "'2025-01-01'" in context
                    found_a_wrapper = True
        assert found_a_wrapper

    def test_merged_cte_has_date_column(self) -> None:
        sql = """WITH
            a AS (SELECT "labno" FROM "KCMH_HIS"."LVST" WHERE "lvstdate" >= '2024-01-01' AND "lvstdate" < '2025-01-01'),
            b AS (SELECT "labno" FROM "KCMH_HIS"."LVST" WHERE "lvstdate" >= '2025-01-01' AND "lvstdate" < '2026-01-01'),
            c AS (SELECT * FROM a UNION ALL SELECT * FROM b)
        SELECT COUNT(*) FROM c"""

        result = optimize_query(sql)
        assert result is not None
        # The merged CTE should include "lvstdate" in its SELECT
        # (because the original SELECT only had "labno", not "lvstdate")
        merged_start = result.find("_lvst_merged AS")
        merged_section = result[merged_start : merged_start + 300]
        assert '"lvstdate"' in merged_section
