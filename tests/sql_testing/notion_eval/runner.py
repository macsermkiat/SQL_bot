"""CLI runner for the Notion-based evaluation pipeline.

Subcommands:
  fetch   -- show instructions for fetching Notion tickets via MCP
  eval    -- run SQL generation + diff against cached tickets
  watch   -- continuous mode: poll cache for new tickets, eval + patch + PR
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from tests.sql_testing.notion_eval.learner import extract_learnings
from tests.sql_testing.notion_eval.notion_loader import (
    load_all_ticket_ids,
    load_tickets,
)
from tests.sql_testing.notion_eval.patcher import accumulate_patches, apply_patches
from tests.sql_testing.notion_eval.report import print_summary, write_report
from tests.sql_testing.notion_eval.scorer import score_results
from tests.sql_testing.notion_eval.sql_diff import diff_sql
from tests.sql_testing.notion_eval.ticket_models import EvalResult, TicketData

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SQL generation helper
# ---------------------------------------------------------------------------

def _generate_sql(description: str) -> tuple[str | None, str | None, float]:
    """Call the app's SQL generator. Returns (sql, error, elapsed_ms)."""
    import time as _time
    t0 = _time.time()
    try:
        from app.sql_gen import get_sql_generator
        generator = get_sql_generator()
        response, _ = generator.generate(description, use_advisor=False)
        elapsed = (_time.time() - t0) * 1000
        if response.needs_clarification:
            return None, f"needs_clarification: {response.clarification_question}", elapsed
        return response.sql, None, elapsed
    except Exception as exc:
        elapsed = (_time.time() - t0) * 1000
        return None, str(exc), elapsed


# ---------------------------------------------------------------------------
# Core pipeline steps
# ---------------------------------------------------------------------------

def _eval_tickets(tickets: list[TicketData]) -> list[EvalResult]:
    results: list[EvalResult] = []
    for i, ticket in enumerate(tickets, 1):
        logger.info(
            "[%d/%d] %s — %s",
            i, len(tickets),
            ticket.ticket_number or ticket.id[:8],
            ticket.title[:50],
        )
        gen_sql, error, elapsed_ms = _generate_sql(ticket.description_thai)

        diff = None
        if gen_sql and not error:
            try:
                diff = diff_sql(
                    ticket_id=ticket.id,
                    gold_sql=ticket.gold_sql,
                    gen_sql=gen_sql,
                    gold_dialect=ticket.gold_sql_dialect,
                )
            except Exception as exc:
                logger.warning("diff_sql failed for %s: %s", ticket.id[:8], exc)
                error = f"diff_error: {exc}"

        results.append(EvalResult(
            ticket=ticket,
            generated_sql=gen_sql,
            generation_error=error,
            diff=diff,
            generation_time_ms=elapsed_ms,
        ))

    return results


def _run_full_pipeline(
    tickets: list[TicketData],
    apply: bool = False,
    dry_run: bool = True,
    auto_pr: bool = False,
    min_support: int = 2,
) -> Path:
    run_id = "run_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger.info("Run ID: %s", run_id)

    results = _eval_tickets(tickets)
    summary = score_results(results)
    print_summary(summary, results)

    all_learnings = []
    for r in results:
        all_learnings.extend(extract_learnings(r))
    logger.info("Total learnings extracted: %d", len(all_learnings))

    proposals = accumulate_patches(all_learnings, min_support=min_support)
    logger.info("Patch proposals (support >= %d): %d", min_support, len(proposals))

    applied = []
    if apply or not dry_run:
        applied = apply_patches(proposals, dry_run=dry_run)
        logger.info("Patches applied: %d", len(applied))
        if applied and auto_pr:
            _create_pr(run_id, len(applied), len(tickets))
    else:
        logger.info("Dry-run mode — patches NOT written. Pass --apply to apply.")

    report_path = write_report(run_id, summary, results, proposals)
    logger.info("Report saved: %s", report_path)
    return report_path


def _create_pr(run_id: str, n_patches: int, n_tickets: int) -> None:
    """Commit schema changes and open a GitHub PR."""
    logger.info("Creating PR for %d patches from %d tickets ...", n_patches, n_tickets)
    try:
        subprocess.run(
            [
                "git", "add",
                "schema/concepts.yaml",
                "schema/sql_corrections.yaml",
                "schema/join_edges.csv",
            ],
            check=True,
        )
        msg = (
            f"feat: auto-training patches from {n_tickets} Notion tickets ({run_id})"
        )
        subprocess.run(["git", "commit", "-m", msg], check=True)
        subprocess.run(["git", "push", "-u", "origin", "HEAD"], check=True)
        body = (
            f"## Auto-training patches\n\n"
            f"- Run: `{run_id}`\n"
            f"- Tickets evaluated: {n_tickets}\n"
            f"- Patches applied: {n_patches}\n\n"
            "Auto-generated by `notion_eval` pipeline. "
            "Review schema diffs before merging."
        )
        subprocess.run(
            [
                "gh", "pr", "create",
                "--title", f"feat: notion eval patches ({run_id})",
                "--body", body,
            ],
            check=True,
        )
        logger.info("PR created successfully.")
    except subprocess.CalledProcessError as exc:
        logger.error("PR creation failed: %s", exc)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tests.sql_testing.notion_eval.runner",
        description="Notion-based evaluation + auto-training pipeline for KCMH SQL bot",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("fetch", help="Show instructions for fetching Notion tickets")

    e = sub.add_parser("eval", help="Run evaluation on cached tickets")
    e.add_argument(
        "--apply", action="store_true",
        help="Apply qualifying patches to schema files",
    )
    e.add_argument(
        "--no-dry-run", dest="dry_run", action="store_false",
        help="Disable dry-run (actually write schema files)",
    )
    e.add_argument(
        "--auto-pr", action="store_true",
        help="Create a GitHub PR after patches are applied",
    )
    e.add_argument(
        "--min-support", type=int, default=2,
        help="Min ticket count to trigger a patch proposal (default: 2)",
    )
    e.add_argument(
        "--limit", type=int, default=0,
        help="Evaluate only first N tickets (0 = all)",
    )
    e.set_defaults(dry_run=True)

    w = sub.add_parser(
        "watch",
        help="Poll cache for new tickets and auto-train (run 'fetch' separately to refresh cache)",
    )
    w.add_argument(
        "--interval", type=int, default=3600,
        help="Poll interval in seconds (default: 3600)",
    )
    w.add_argument("--auto-pr", action="store_true")
    w.add_argument("--min-support", type=int, default=2)

    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.cmd == "fetch":
        print(
            "The 'fetch' subcommand requires the Notion MCP tool.\n"
            "Run it inside a Claude Code session with Notion MCP active:\n\n"
            "  python -m tests.sql_testing.notion_eval.runner fetch\n\n"
            "Or ask Claude to run: notion_loader.save_cache(tickets) after fetching."
        )
        sys.exit(0)

    elif args.cmd == "eval":
        tickets = load_tickets()
        if args.limit:
            tickets = tickets[: args.limit]
        logger.info("Evaluating %d tickets ...", len(tickets))
        _run_full_pipeline(
            tickets,
            apply=args.apply,
            dry_run=args.dry_run,
            auto_pr=args.auto_pr,
            min_support=args.min_support,
        )

    elif args.cmd == "watch":
        logger.info("Watch mode — polling every %ds", args.interval)
        seen_ids = load_all_ticket_ids()
        while True:
            tickets = load_tickets()
            new_tickets = [t for t in tickets if t.id not in seen_ids]
            if new_tickets:
                logger.info(
                    "Found %d new ticket(s) — running training pipeline",
                    len(new_tickets),
                )
                _run_full_pipeline(
                    new_tickets,
                    apply=True,
                    dry_run=False,
                    auto_pr=args.auto_pr,
                    min_support=args.min_support,
                )
                seen_ids.update(t.id for t in new_tickets)
            else:
                logger.info("No new tickets. Sleeping %ds ...", args.interval)
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
