"""Unit tests for scorer.py — RunSummary aggregation and grade()."""

from tests.sql_testing.notion_eval.scorer import grade, score_results
from tests.sql_testing.notion_eval.ticket_models import (
    EvalResult,
    SqlDiffResult,
    TicketData,
)


def _make_ticket(ticket_id: str = "t1", dept: str = "อายุรศาสตร์") -> TicketData:
    return TicketData(
        id=ticket_id,
        title="Test ticket",
        notion_url="https://notion.so/test",
        ticket_number="TEST-001",
        department=dept,
        status="Done",
        purpose="testing",
        data_level=["aggregate"],
        created_at="2026-01-01",
        description_thai="ทดสอบ",
        gold_sql="SELECT COUNT(*) FROM PTDIAG",
        has_phi_concern=False,
        gold_sql_dialect="oracle",
    )


def _make_diff(score: float) -> SqlDiffResult:
    return SqlDiffResult(
        ticket_id="t1",
        gold_tables={"PTDIAG"},
        gen_tables={"PTDIAG"},
        gold_joins=[],
        gen_joins=[],
        gold_filters=[],
        gen_filters=[],
        gold_aggregates=[],
        gen_aggregates=[],
        table_recall=score,
        table_precision=score,
        join_recall=score,
        filter_recall=score,
        aggregate_recall=score,
        overall_score=score,
    )


def _make_result(score: float, success: bool = True, dept: str = "อายุรศาสตร์") -> EvalResult:
    ticket = _make_ticket(dept=dept)
    return EvalResult(
        ticket=ticket,
        generated_sql="SELECT COUNT(*) FROM PTDIAG" if success else None,
        generation_error=None if success else "mock error",
        diff=_make_diff(score) if success else None,
        generation_time_ms=100.0,
    )


class TestGrade:
    def test_pass(self):
        assert grade(_make_result(0.80)) == "PASS"

    def test_warn(self):
        assert grade(_make_result(0.60)) == "WARN"

    def test_fail(self):
        assert grade(_make_result(0.30)) == "FAIL"

    def test_skip_on_generation_failure(self):
        assert grade(_make_result(0.0, success=False)) == "SKIP"

    def test_boundary_pass_threshold(self):
        assert grade(_make_result(0.70)) == "PASS"

    def test_boundary_warn_threshold(self):
        assert grade(_make_result(0.50)) == "WARN"


class TestScoreResults:
    def test_empty_list(self):
        summary = score_results([])
        assert summary.total == 0
        assert summary.pass_rate == 0.0

    def test_counts_correct(self):
        results = [
            _make_result(0.80),
            _make_result(0.55),
            _make_result(0.20),
            _make_result(0.0, success=False),
        ]
        summary = score_results(results)
        assert summary.total == 4
        assert summary.passed == 1
        assert summary.warned == 1
        assert summary.failed == 1
        assert summary.skipped == 1

    def test_avg_score_calculated(self):
        results = [_make_result(0.80), _make_result(0.60)]
        summary = score_results(results)
        assert abs(summary.avg_score - 0.70) < 1e-9

    def test_pass_rate_percent(self):
        results = [_make_result(0.80), _make_result(0.80), _make_result(0.20)]
        summary = score_results(results)
        assert abs(summary.pass_rate - (2 / 3 * 100)) < 1e-6

    def test_per_department_grouping(self):
        results = [
            _make_result(0.80, dept="อายุรศาสตร์"),
            _make_result(0.70, dept="อายุรศาสตร์"),
            _make_result(0.50, dept="ศัลยศาสตร์"),
        ]
        summary = score_results(results)
        assert "อายุรศาสตร์" in summary.per_department
        assert len(summary.per_department["อายุรศาสตร์"]) == 2
        assert len(summary.per_department["ศัลยศาสตร์"]) == 1

    def test_all_skipped_gives_zero_avg(self):
        results = [_make_result(0.0, success=False)] * 3
        summary = score_results(results)
        assert summary.avg_score == 0.0
        assert summary.skipped == 3
