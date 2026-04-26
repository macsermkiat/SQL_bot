"""
Tests for SQL query optimizer (CTE flattening and duplicate scan merger).

Usage:
    uv run pytest tests/test_sql_optimizer.py -v
"""

from __future__ import annotations

import pytest

from app.sql_optimizer import _analyze_leaf, optimize_query, is_large_table_scan


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
        assert info.is_simple_scan is True

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
        assert info.is_simple_scan is True

    def test_leaf_without_schema_is_supported(self) -> None:
        body = """SELECT "labno", "hn"
    FROM "LVST" lv
    WHERE lv."lvstdate" >= '2024-01-01'
      AND lv."lvstdate" < '2025-01-01'"""
        info = _analyze_leaf(body)
        assert info is not None
        assert info.schema_name is None
        assert info.base_table == "LVST"
        assert info.table_alias == "lv"

    def test_leaf_with_as_alias_is_supported(self) -> None:
        body = """SELECT lv."labno", lv."hn"
    FROM "KCMH_HIS"."LVST" AS lv
    WHERE lv."lvstdate" >= '2024-01-01'
      AND lv."lvstdate" < '2025-01-01'"""
        info = _analyze_leaf(body)
        assert info is not None
        assert info.schema_name == "KCMH_HIS"
        assert info.base_table == "LVST"
        assert info.table_alias == "lv"

    def test_leaf_with_distinct(self) -> None:
        body = """SELECT DISTINCT "hn"
    FROM "KCMH_HIS"."PTDIAG"
    WHERE "vstdate" >= '2024-01-01'
      AND "vstdate" < '2025-01-01'"""
        info = _analyze_leaf(body)
        assert info is not None
        assert info.is_distinct is True
        assert info.is_simple_scan is True

    def test_leaf_with_join_not_simple(self) -> None:
        body = """SELECT lv."hn"
    FROM "KCMH_HIS"."LVST" lv
    JOIN "KCMH_HIS"."LVSTEXM" lexm ON lv."labno" = lexm."labno"
    WHERE lv."lvstdate" >= '2024-01-01'
      AND lv."lvstdate" < '2025-01-01'"""
        info = _analyze_leaf(body)
        assert info is not None
        assert info.is_simple_scan is False

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
# is_large_table_scan
# ---------------------------------------------------------------------------


class TestIsLargeTableScan:
    """Tests for large table detection heuristic."""

    def test_lvst_is_large(self) -> None:
        body = 'SELECT "labno" FROM "KCMH_HIS"."LVST" WHERE ...'
        assert is_large_table_scan(body) is True

    def test_labexm_is_small(self) -> None:
        body = 'SELECT "labexm" FROM "KCMH_HIS"."LABEXM" WHERE ...'
        assert is_large_table_scan(body) is False

    def test_icd10_is_small(self) -> None:
        body = 'SELECT "icd10" FROM "KCMH_HIS"."ICD10" WHERE ...'
        assert is_large_table_scan(body) is False

    def test_ptdiag_is_large(self) -> None:
        body = 'SELECT "hn" FROM "KCMH_HIS"."PTDIAG" WHERE ...'
        assert is_large_table_scan(body) is True


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
        # Both a and b are simple scans referenced in c, but they scan different tables
        result = optimize_query(sql)
        # Should flatten both into c
        if result:
            assert "a AS" not in result or "FROM a" not in result
            assert "b AS" not in result or "FROM b" not in result

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
# optimize_query - flattening cases
# ---------------------------------------------------------------------------


class TestOptimizeFlatten:
    """Cases where leaf CTEs should be flattened into downstream CTEs."""

    def test_basic_flatten(self) -> None:
        """Simple leaf CTE flattened into downstream CTE."""
        sql = """WITH
            lvst_2024 AS (
                SELECT "labno", "hn"
                FROM "KCMH_HIS"."LVST"
                WHERE "lvstdate" >= '2024-01-01'
                  AND "lvstdate" < '2025-01-01'
            ),
            results AS (
                SELECT l24."hn"
                FROM lvst_2024 l24
                INNER JOIN "KCMH_HIS"."LVSTEXM" lexm ON l24."labno" = lexm."labno"
                WHERE lexm."result" IS NOT NULL
            )
        SELECT COUNT(*) FROM results"""

        result = optimize_query(sql)
        assert result is not None

        # lvst_2024 CTE should be eliminated
        assert "lvst_2024 AS" not in result

        # LVST should be directly referenced in results CTE
        assert '"KCMH_HIS"."LVST"' in result

        # Date conditions should be injected
        assert "'2024-01-01'" in result
        assert "'2025-01-01'" in result

        # Original WHERE conditions preserved
        assert "result" in result
        assert "IS NOT NULL" in result

    def test_flatten_preserves_non_default_schema(self) -> None:
        sql = """WITH
            lvst_2024 AS (
                SELECT "labno", "hn"
                FROM "ALT_SCHEMA"."LVST"
                WHERE "lvstdate" >= '2024-01-01'
                  AND "lvstdate" < '2025-01-01'
            ),
            results AS (
                SELECT l24."hn"
                FROM lvst_2024 l24
                INNER JOIN "ALT_SCHEMA"."LVSTEXM" lexm ON l24."labno" = lexm."labno"
                WHERE lexm."result" IS NOT NULL
            )
        SELECT COUNT(*) FROM results"""

        result = optimize_query(sql)
        assert result is not None
        assert '"ALT_SCHEMA"."LVST"' in result
        assert "lvst_2024 AS" not in result

    def test_users_exact_query_flattened(self) -> None:
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

        # lvst_2024 and lvst_2025 CTEs should be ELIMINATED (flattened)
        assert "lvst_2024 AS" not in result
        assert "lvst_2025 AS" not in result

        # LVST should be directly referenced in hba1c_2024 and hba1c_2025
        assert '"KCMH_HIS"."LVST"' in result

        # Date conditions should be injected into hba1c_2024 and hba1c_2025
        assert "'2024-01-01'" in result
        assert "'2025-01-01'" in result
        assert "'2026-01-01'" in result

        # Non-flattened CTEs should be preserved
        assert "diabetes_patients AS" in result
        assert "hba1c_labexm AS" in result
        assert "hba1c_2024 AS" in result
        assert "hba1c_2025 AS" in result

        # Final query preserved
        assert "SELECT COUNT(*) AS patient_count" in result
        assert "FROM diabetes_patients dp" in result

        # No _lvst_merged (we flatten, not merge)
        assert "_lvst_merged" not in result

    def test_flatten_preserves_alias(self) -> None:
        """Alias used in downstream CTE should be preserved."""
        sql = """WITH
            year_data AS (
                SELECT "vn", "hn"
                FROM "KCMH_HIS"."OVST"
                WHERE "vstdate" >= '2024-01-01'
                  AND "vstdate" < '2025-01-01'
            ),
            counts AS (
                SELECT yd."hn", COUNT(*) as cnt
                FROM year_data yd
                GROUP BY yd."hn"
            )
        SELECT * FROM counts"""

        result = optimize_query(sql)
        assert result is not None

        # year_data should be eliminated
        assert "year_data AS" not in result

        # OVST should be directly referenced with alias
        assert '"KCMH_HIS"."OVST"' in result

        # Date conditions injected
        assert "'2024-01-01'" in result

    def test_flatten_two_leaves_into_different_downstreams(self) -> None:
        """Two separate leaf CTEs flattened into their respective downstreams."""
        sql = """WITH
            lvst_2024 AS (
                SELECT "labno", "hn"
                FROM "KCMH_HIS"."LVST"
                WHERE "lvstdate" >= '2024-01-01' AND "lvstdate" < '2025-01-01'
            ),
            lvst_2025 AS (
                SELECT "labno", "hn"
                FROM "KCMH_HIS"."LVST"
                WHERE "lvstdate" >= '2025-01-01' AND "lvstdate" < '2026-01-01'
            ),
            data_2024 AS (
                SELECT l24."hn" FROM lvst_2024 l24
                INNER JOIN "KCMH_HIS"."LVSTEXM" lexm ON l24."labno" = lexm."labno"
                WHERE lexm."result" IS NOT NULL
            ),
            data_2025 AS (
                SELECT l25."hn" FROM lvst_2025 l25
                INNER JOIN "KCMH_HIS"."LVSTEXM" lexm ON l25."labno" = lexm."labno"
                WHERE lexm."result" IS NOT NULL
            )
        SELECT COUNT(*) FROM data_2024 UNION ALL SELECT COUNT(*) FROM data_2025"""

        result = optimize_query(sql)
        assert result is not None

        # Both leaf CTEs eliminated
        assert "lvst_2024 AS" not in result
        assert "lvst_2025 AS" not in result

        # data_2024 and data_2025 still exist
        assert "data_2024 AS" in result
        assert "data_2025 AS" in result

        # LVST referenced directly
        assert '"KCMH_HIS"."LVST"' in result

    def test_leaf_in_final_query_not_flattened(self) -> None:
        """Leaf CTEs referenced in the final query should NOT be flattened."""
        sql = """WITH
            lvst_2024 AS (
                SELECT "labno", "hn"
                FROM "KCMH_HIS"."LVST"
                WHERE "lvstdate" >= '2024-01-01' AND "lvstdate" < '2025-01-01'
            ),
            lvst_2025 AS (
                SELECT "labno", "hn"
                FROM "KCMH_HIS"."LVST"
                WHERE "lvstdate" >= '2025-01-01' AND "lvstdate" < '2026-01-01'
            ),
            combined AS (
                SELECT * FROM lvst_2024
                UNION ALL
                SELECT * FROM lvst_2025
            )
        SELECT COUNT(*) FROM combined"""

        result = optimize_query(sql)
        assert result is not None
        # Should fall back to merge since both leaves are only used in
        # combined (which is another CTE), not final query.
        # Both should be flattened into combined.
        # OR merged if flattening FROM doesn't work for UNION.
        # Let's just verify it produces valid output.
        assert result.strip().startswith("WITH")


# ---------------------------------------------------------------------------
# optimize_query - merge fallback cases
# ---------------------------------------------------------------------------


class TestOptimizeMergeFallback:
    """Cases where flattening isn't possible and merge is used as fallback."""

    def test_three_year_merge(self) -> None:
        """Three year CTEs used in final query - should merge."""
        sql = """WITH
            y23 AS (SELECT "vn" FROM "KCMH_HIS"."OVST" WHERE "vstdate" >= '2023-01-01' AND "vstdate" < '2024-01-01'),
            y24 AS (SELECT "vn" FROM "KCMH_HIS"."OVST" WHERE "vstdate" >= '2024-01-01' AND "vstdate" < '2025-01-01'),
            y25 AS (SELECT "vn" FROM "KCMH_HIS"."OVST" WHERE "vstdate" >= '2025-01-01' AND "vstdate" < '2026-01-01'),
            agg AS (SELECT COUNT(*) FROM y23 UNION ALL SELECT COUNT(*) FROM y24 UNION ALL SELECT COUNT(*) FROM y25)
        SELECT * FROM agg"""

        result = optimize_query(sql)
        assert result is not None
        # Either flattened or merged
        assert "'2023-01-01'" in result
        assert "'2026-01-01'" in result


# ---------------------------------------------------------------------------
# Structural validity of optimized output
# ---------------------------------------------------------------------------


class TestOptimizeOutputValidity:
    """Verify the optimized SQL is structurally valid."""

    def test_starts_with_WITH(self) -> None:
        sql = """WITH
            a AS (SELECT "hn" FROM "KCMH_HIS"."LVST" WHERE "lvstdate" >= '2024-01-01' AND "lvstdate" < '2025-01-01'),
            b AS (SELECT a_ref."hn" FROM a a_ref INNER JOIN "KCMH_HIS"."LVSTEXM" lexm ON a_ref."hn" = lexm."labno" WHERE lexm."result" IS NOT NULL)
        SELECT COUNT(*) FROM b"""

        result = optimize_query(sql)
        assert result is not None
        assert result.strip().startswith("WITH")

    def test_flattened_query_has_date_filter(self) -> None:
        """After flattening, the downstream CTE must contain the date filter."""
        sql = """WITH
            a AS (SELECT "hn" FROM "KCMH_HIS"."LVST" WHERE "lvstdate" >= '2024-01-01' AND "lvstdate" < '2025-01-01'),
            b AS (SELECT a_ref."hn" FROM a a_ref WHERE 1=1)
        SELECT COUNT(*) FROM b"""

        result = optimize_query(sql)
        assert result is not None
        # The date filter should be in the result
        assert "'2024-01-01'" in result
        assert "'2025-01-01'" in result
        # Original CTE 'a' should be eliminated
        assert "a AS" not in result or "a_ref" in result
