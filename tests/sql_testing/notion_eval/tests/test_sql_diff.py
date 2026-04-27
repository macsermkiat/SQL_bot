"""Unit tests for sql_diff.py — structural SQL comparison."""

import pytest

from tests.sql_testing.notion_eval.sql_diff import diff_sql


_GOLD_ORACLE = """
SELECT COUNT(*) AS cnt
FROM CUH.PTDIAG pd
JOIN CUH.IPT ipt ON pd.hn = ipt.hn
WHERE pd.icd10 LIKE 'E11%'
  AND ipt.dchdate >= TO_DATE('2024-01-01', 'YYYY-MM-DD')
"""

_GEN_MATCH = """
SELECT COUNT(*) AS cnt
FROM PTDIAG pd
JOIN IPT ipt ON pd.hn = ipt.hn
WHERE pd.icd10 LIKE 'E11%'
  AND ipt.dchdate >= '2024-01-01'
"""

_GEN_MISSING_TABLE = """
SELECT COUNT(*) AS cnt
FROM PTDIAG pd
WHERE pd.icd10 LIKE 'E11%'
"""

_GEN_EXTRA_TABLE = """
SELECT COUNT(*) AS cnt
FROM PTDIAG pd
JOIN IPT ipt ON pd.hn = ipt.hn
JOIN OVST ov ON ov.hn = pd.hn
WHERE pd.icd10 LIKE 'E11%'
"""

_GOLD_SQLSERVER = """
SELECT COUNT(*) AS cnt
FROM ddc_internal.PTDIAG pd
JOIN ddc_internal.IPT ipt ON pd.hn = ipt.hn
WHERE YEAR(ipt.dchdate) = 2024
"""


class TestDiffSqlTableRecall:
    def test_perfect_match_gives_full_table_recall(self):
        result = diff_sql("T001", _GOLD_ORACLE, _GEN_MATCH, gold_dialect="oracle")
        assert result.table_recall == 1.0

    def test_missing_table_reduces_recall(self):
        result = diff_sql("T002", _GOLD_ORACLE, _GEN_MISSING_TABLE, gold_dialect="oracle")
        assert result.table_recall < 1.0
        assert "IPT" in result.missing_tables

    def test_extra_table_recorded(self):
        result = diff_sql("T003", _GOLD_ORACLE, _GEN_EXTRA_TABLE, gold_dialect="oracle")
        assert "OVST" in result.extra_tables

    def test_schema_prefix_stripped_oracle(self):
        result = diff_sql("T004", _GOLD_ORACLE, _GEN_MATCH, gold_dialect="oracle")
        assert "PTDIAG" in result.gold_tables
        assert "IPT" in result.gold_tables

    def test_schema_prefix_stripped_sqlserver(self):
        result = diff_sql("T005", _GOLD_SQLSERVER, _GEN_MATCH, gold_dialect="sqlserver")
        assert "PTDIAG" in result.gold_tables


class TestDiffSqlOverallScore:
    def test_full_match_score_above_pass_threshold(self):
        result = diff_sql("T010", _GOLD_ORACLE, _GEN_MATCH, gold_dialect="oracle")
        assert result.overall_score >= 0.7

    def test_missing_table_lowers_overall_score(self):
        result_match = diff_sql("T011a", _GOLD_ORACLE, _GEN_MATCH, gold_dialect="oracle")
        result_miss = diff_sql("T011b", _GOLD_ORACLE, _GEN_MISSING_TABLE, gold_dialect="oracle")
        assert result_miss.overall_score < result_match.overall_score

    def test_ticket_id_propagated(self):
        result = diff_sql("TICKET-XYZ", _GOLD_ORACLE, _GEN_MATCH, gold_dialect="oracle")
        assert result.ticket_id == "TICKET-XYZ"

    def test_score_components_sum_correctly(self):
        result = diff_sql("T012", _GOLD_ORACLE, _GEN_MATCH, gold_dialect="oracle")
        expected = (
            0.40 * result.table_recall
            + 0.30 * result.join_recall
            + 0.20 * result.filter_recall
            + 0.10 * result.aggregate_recall
        )
        assert abs(result.overall_score - expected) < 1e-9


class TestDiffSqlEdgeCases:
    def test_trivial_sql_gives_recall_one(self):
        result = diff_sql("T020", "SELECT 1", "SELECT 1", gold_dialect="oracle")
        assert result.table_recall == 1.0

    def test_sqlglot_unavailable_graceful(self, monkeypatch):
        import tests.sql_testing.notion_eval.sql_diff as sd
        monkeypatch.setattr(sd, "_SQLGLOT_AVAILABLE", False)
        result = diff_sql("T021", _GOLD_ORACLE, _GEN_MATCH, gold_dialect="oracle")
        assert result.parse_error == "sqlglot not installed"
