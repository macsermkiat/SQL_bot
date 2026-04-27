"""Unit tests for learner.py — learning extraction from eval results."""

from tests.sql_testing.notion_eval.learner import extract_learnings
from tests.sql_testing.notion_eval.ticket_models import (
    EvalResult,
    SqlDiffResult,
    TicketData,
)


def _make_ticket(ticket_id: str = "abc123") -> TicketData:
    return TicketData(
        id=ticket_id,
        title="Lab test count",
        notion_url="https://notion.so/test",
        ticket_number="OPH-001",
        department="จักษุวิทยา",
        status="Done",
        purpose="count",
        data_level=["aggregate"],
        created_at="2026-01-01",
        description_thai="จำนวนผู้ป่วยที่ตรวจ lab",
        gold_sql="SELECT COUNT(*) FROM LABRESULT JOIN IPT ON LABRESULT.an = IPT.an",
        has_phi_concern=False,
        gold_sql_dialect="oracle",
    )


def _make_result(
    missing_tables: set | None = None,
    extra_tables: set | None = None,
    missing_joins: list | None = None,
    missing_filters: list | None = None,
    gen_sql: str = "SELECT COUNT(*) FROM PTDIAG",
    success: bool = True,
) -> EvalResult:
    ticket = _make_ticket()
    diff = SqlDiffResult(
        ticket_id=ticket.id,
        gold_tables={"LABRESULT", "IPT"},
        gen_tables={"PTDIAG"},
        gold_joins=[("LABRESULT.AN", "IPT.AN")],
        gen_joins=[],
        gold_filters=[],
        gen_filters=[],
        gold_aggregates=[],
        gen_aggregates=[],
        table_recall=0.0,
        table_precision=0.0,
        join_recall=0.0,
        filter_recall=1.0,
        aggregate_recall=1.0,
        overall_score=0.0,
        missing_tables=missing_tables if missing_tables is not None else set(),
        extra_tables=extra_tables if extra_tables is not None else set(),
        missing_joins=missing_joins if missing_joins is not None else [],
        missing_filters=missing_filters if missing_filters is not None else [],
    )
    return EvalResult(
        ticket=ticket,
        generated_sql=gen_sql if success else None,
        generation_error=None if success else "mock error",
        diff=diff if success else None,
        generation_time_ms=200.0,
    )


class TestExtractLearnings:
    def test_no_learnings_on_failure(self):
        result = _make_result(success=False)
        assert extract_learnings(result) == []

    def test_missing_table_produces_learning(self):
        result = _make_result(missing_tables={"LABRESULT"})
        types = [l.learning_type for l in extract_learnings(result)]
        assert "missing_table" in types

    def test_missing_table_targets_concepts_yaml(self):
        result = _make_result(missing_tables={"LABRESULT"})
        learnings = [l for l in extract_learnings(result) if l.learning_type == "missing_table"]
        assert all(l.target_file == "concepts.yaml" for l in learnings)

    def test_extra_table_produces_learning(self):
        result = _make_result(extra_tables={"OVST"})
        types = [l.learning_type for l in extract_learnings(result)]
        assert "extra_table" in types

    def test_missing_join_produces_learning(self):
        result = _make_result(missing_joins=[("LABRESULT.AN", "IPT.AN")])
        types = [l.learning_type for l in extract_learnings(result)]
        assert "missing_join" in types

    def test_missing_join_targets_join_edges_csv(self):
        result = _make_result(missing_joins=[("LABRESULT.AN", "IPT.AN")])
        learnings = [l for l in extract_learnings(result) if l.learning_type == "missing_join"]
        assert all(l.target_file == "join_edges.csv" for l in learnings)

    def test_missing_filter_produces_learning(self):
        result = _make_result(missing_filters=["STATUS = 'A'"])
        types = [l.learning_type for l in extract_learnings(result)]
        assert "missing_filter" in types

    def test_icd_format_issue_detected(self):
        ticket = _make_ticket()
        clean_ticket = TicketData(
            id=ticket.id,
            title=ticket.title,
            notion_url=ticket.notion_url,
            ticket_number=ticket.ticket_number,
            department=ticket.department,
            status=ticket.status,
            purpose=ticket.purpose,
            data_level=ticket.data_level,
            created_at=ticket.created_at,
            description_thai=ticket.description_thai,
            gold_sql="SELECT * FROM PTDIAG WHERE icd10 LIKE 'E11%'",
            has_phi_concern=ticket.has_phi_concern,
            gold_sql_dialect=ticket.gold_sql_dialect,
        )
        diff = SqlDiffResult(
            ticket_id=clean_ticket.id,
            gold_tables={"PTDIAG"}, gen_tables={"PTDIAG"},
            gold_joins=[], gen_joins=[],
            gold_filters=[], gen_filters=[],
            gold_aggregates=[], gen_aggregates=[],
            overall_score=0.9,
            missing_tables=set(), extra_tables=set(),
            missing_joins=[], missing_filters=[],
        )
        result = EvalResult(
            ticket=clean_ticket,
            generated_sql="SELECT * FROM PTDIAG WHERE icd10 LIKE 'E11.9%'",
            generation_error=None,
            diff=diff,
        )
        types = [l.learning_type for l in extract_learnings(result)]
        assert "wrong_icd_format" in types

    def test_ticket_id_propagated(self):
        result = _make_result(missing_tables={"LABRESULT"})
        assert all(l.ticket_id == "abc123" for l in extract_learnings(result))

    def test_empty_diff_no_structural_learnings(self):
        result = _make_result(
            missing_tables=set(),
            extra_tables=set(),
            missing_joins=[],
            missing_filters=[],
        )
        structural = [
            l for l in extract_learnings(result)
            if l.learning_type in ("missing_table", "extra_table", "missing_join", "missing_filter", "wrong_icd_format")
        ]
        assert len(structural) == 0
