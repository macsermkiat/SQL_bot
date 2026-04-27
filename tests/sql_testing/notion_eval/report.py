"""Format and persist evaluation reports."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from tests.sql_testing.notion_eval.scorer import RunSummary, grade
from tests.sql_testing.notion_eval.ticket_models import EvalResult, PatchProposal

logger = logging.getLogger(__name__)

_RESULTS_ROOT = (
    Path(__file__).parent.parent.parent.parent
    / "test_data"
    / "sql_testing"
    / "results"
)


def _run_id() -> str:
    return "run_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def print_summary(summary: RunSummary, results: list[EvalResult]) -> None:
    """Print a human-readable summary table to stdout."""
    print("\n" + "=" * 70)
    print(f"  Notion Eval — {summary.total} tickets")
    print("=" * 70)
    print(
        f"  PASS {summary.passed:>4}  |  WARN {summary.warned:>4}  |"
        f"  FAIL {summary.failed:>4}  |  SKIP {summary.skipped:>4}"
    )
    print(f"  Pass rate : {summary.pass_rate:.1f}%")
    print(f"  Avg score : {summary.avg_score:.3f}")
    print(f"  Table recall  : {summary.avg_table_recall:.3f}")
    print(f"  Join recall   : {summary.avg_join_recall:.3f}")
    print(f"  Filter recall : {summary.avg_filter_recall:.3f}")

    if summary.per_department:
        print("\n  Per department:")
        for dept, scores in sorted(summary.per_department.items()):
            avg = sum(scores) / len(scores)
            print(f"    {dept:<30} avg={avg:.3f}  n={len(scores)}")

    print("\n  Per-ticket results:")
    print(f"  {'#':<6} {'Grade':<6} {'Score':>6}  {'Dept':<20}  Title")
    print("  " + "-" * 66)
    for r in results:
        g = grade(r)
        score_str = f"{r.score:.3f}" if r.is_success else "  N/A"
        dept = (r.ticket.department or "—")[:18]
        title = r.ticket.title[:35]
        num = r.ticket.ticket_number or r.ticket.id[:6]
        print(f"  {num:<6} {g:<6} {score_str:>6}  {dept:<20}  {title}")

    print("=" * 70 + "\n")


def write_report(
    run_id: str,
    summary: RunSummary,
    results: list[EvalResult],
    patches: list[PatchProposal],
    output_dir: Path | None = None,
) -> Path:
    """Write a JSON report to disk. Returns the path written."""
    out_dir = (output_dir or _RESULTS_ROOT) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "notion_eval_report.json"

    payload = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": summary.total,
            "passed": summary.passed,
            "warned": summary.warned,
            "failed": summary.failed,
            "skipped": summary.skipped,
            "pass_rate": round(summary.pass_rate, 2),
            "avg_score": round(summary.avg_score, 4),
            "avg_table_recall": round(summary.avg_table_recall, 4),
            "avg_join_recall": round(summary.avg_join_recall, 4),
            "avg_filter_recall": round(summary.avg_filter_recall, 4),
            "per_department": {
                dept: round(sum(s) / len(s), 4)
                for dept, s in summary.per_department.items()
            },
        },
        "patches_proposed": len(patches),
        "patches_applied": sum(1 for p in patches if p.applied),
        "results": [_result_to_dict(r) for r in results],
        "patch_proposals": [_patch_to_dict(p) for p in patches],
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=_json_default)

    logger.info("Report written to %s", report_path)
    return report_path


def _result_to_dict(r: EvalResult) -> dict:
    d: dict = {
        "ticket_id": r.ticket.id,
        "ticket_number": r.ticket.ticket_number,
        "title": r.ticket.title,
        "department": r.ticket.department,
        "grade": grade(r),
        "score": round(r.score, 4),
        "generation_time_ms": round(r.generation_time_ms, 1),
        "generation_error": r.generation_error,
    }
    if r.diff:
        d["diff"] = {
            "table_recall": round(r.diff.table_recall, 4),
            "join_recall": round(r.diff.join_recall, 4),
            "filter_recall": round(r.diff.filter_recall, 4),
            "aggregate_recall": round(r.diff.aggregate_recall, 4),
            "missing_tables": sorted(r.diff.missing_tables),
            "extra_tables": sorted(r.diff.extra_tables),
            "missing_joins": [list(j) for j in r.diff.missing_joins],
            "missing_filters": r.diff.missing_filters[:10],
            "parse_error": r.diff.parse_error,
        }
    return d


def _patch_to_dict(p: PatchProposal) -> dict:
    return {
        "patch_id": p.patch_id,
        "title": p.title,
        "target_file": p.target_file,
        "patch_type": p.patch_type,
        "support_count": p.support_count,
        "applied": p.applied,
        "affected_tickets": p.affected_tickets[:10],
    }


def _json_default(obj: object) -> object:
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"Not serializable: {type(obj)}")
