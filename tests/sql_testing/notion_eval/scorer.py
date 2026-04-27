"""Score a batch of evaluation results and produce summary statistics."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from tests.sql_testing.notion_eval.ticket_models import EvalResult

logger = logging.getLogger(__name__)

_PASS_THRESHOLD = 0.70
_WARN_THRESHOLD = 0.50


@dataclass
class RunSummary:
    total: int = 0
    passed: int = 0
    warned: int = 0
    failed: int = 0
    skipped: int = 0
    avg_score: float = 0.0
    avg_table_recall: float = 0.0
    avg_join_recall: float = 0.0
    avg_filter_recall: float = 0.0
    per_department: dict[str, list[float]] = field(default_factory=dict)

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total * 100


def score_results(results: list[EvalResult]) -> RunSummary:
    """Aggregate a list of EvalResult into a RunSummary."""
    summary = RunSummary(total=len(results))

    scores: list[float] = []
    table_recalls: list[float] = []
    join_recalls: list[float] = []
    filter_recalls: list[float] = []

    for r in results:
        if not r.is_success:
            summary.skipped += 1
            continue

        s = r.score
        scores.append(s)

        if r.diff:
            table_recalls.append(r.diff.table_recall)
            join_recalls.append(r.diff.join_recall)
            filter_recalls.append(r.diff.filter_recall)

            dept = r.ticket.department or "Unknown"
            summary.per_department.setdefault(dept, []).append(s)

        if s >= _PASS_THRESHOLD:
            summary.passed += 1
        elif s >= _WARN_THRESHOLD:
            summary.warned += 1
        else:
            summary.failed += 1

    if scores:
        summary.avg_score = sum(scores) / len(scores)
    if table_recalls:
        summary.avg_table_recall = sum(table_recalls) / len(table_recalls)
    if join_recalls:
        summary.avg_join_recall = sum(join_recalls) / len(join_recalls)
    if filter_recalls:
        summary.avg_filter_recall = sum(filter_recalls) / len(filter_recalls)

    return summary


def grade(result: EvalResult) -> str:
    """Return PASS / WARN / FAIL / SKIP for a single result."""
    if not result.is_success:
        return "SKIP"
    s = result.score
    if s >= _PASS_THRESHOLD:
        return "PASS"
    if s >= _WARN_THRESHOLD:
        return "WARN"
    return "FAIL"
