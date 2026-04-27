"""CLI runner for the Notion-based evaluation pipeline.

Subcommands:
  fetch   -- show instructions for fetching Notion tickets via MCP
  eval    -- run SQL generation + diff against cached tickets
  watch   -- continuous mode: poll cache for new tickets, eval + patch + PR

Flags:
  --execute   Also run both SQLs against the live DB and compare rowcounts.
              Requires VPN + DATABASE_URL set in .env (on user's machine).
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
from tests.sql_testing.notion_eval.ticket_models import EvalResult, ExecutionResult, TicketData

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

def _eval_tickets(
    tickets: list[TicketData],
    execute: bool = False,
) -> tuple[list[EvalResult], list[ExecutionResult]]:
    results: list[EvalResult] = []
    exec_results: list[ExecutionResult] = []

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

        if execute and gen_sql and not error:
            try:
                from tests.sql_testing.notion_eval.sql_executor import execute_both
                exec_result = execute_both(ticket, gen_sql)
                exec_results.append(exec_result)
            except Exception as exc:
                logger.error("execute_both failed for %s: %s", ticket.id[:8], exc)

    return results, exec_results


def _print_execution_summary(exec_results: list[ExecutionResult]) -> None:
    if not exec_results:
        return
    matched = sum(1 for r in exec_results if r.rowcount_match)
    both_ok = sum(1 for r in exec_results if r.both_succeeded)
    print("\n  --- Live DB execution ---")
    print(f"  Executed : {len(exec_results)}")
    print(f"  Both OK  : {both_ok}")
    print(f"  Rowcount match : {matched} / {both_ok}")
    print(f"\n  {'#':<6} {'Match':<6} {'Gen rows':>9} {'Gold rows':>10}  Title")
    print("  " + "-" * 55)
    for r in exec_results:
        ticket_num = r.ticket_id[:6]
        match = "YES" if r.rowcount_match else ("ERR" if not r.both_succeeded else "NO")
        gen = str(r.gen_row_count) if r.gen_error is None else "ERR"
        gold = str(r.gold_row_count) if r.gold_error is None else "ERR"
        print(f"  {ticket_num:<6} {match:<6} {gen:>9} {gold:>10}")


def _run_full_pipeline(
    tickets: list[TicketData],
    apply: bool = False,
    dry_run: bool = True,
    auto_pr: bool = False,
    min_support: int = 2,
    execute: bool = False,
) -> Path:
    run_id = "run_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger.info("Run ID: %s", run_id)

    results, exec_results = _eval_tickets(tickets, execute=execute)
    summary = score_results(results)
    print_summary(summary, results)

    if execute:
        _print_execution_summary(exec_results)

    all_learnings = []
    for r in results:
        all_learnings.extend(extract_learnings(r))
    logger.info("Total learnings extracted: %d", len(all_learnings))

    proposals = accumulate_patches(all_learnings, min_support=min_support)
    logger.info("Patch proposals (support >= %d): %d", min_support, len(proposals))

    applied = []
    if apply or not dry_run:
        try:
            applied = apply_patches(proposals, dry_run=dry_run)
            logger.info("Patches applied: %d", len(applied))
            if applied and auto_pr:
                _create_pr(run_id, len(applied), len(tickets))
        except RuntimeError as exc:
            logger.error("Patch application failed — auto-PR aborted: %s", exc)
    else:
        logger.info("Dry-run mode — patches NOT written. Pass --apply to apply.")

    report_path = write_report(run_id, summary, results, proposals, exec_results=exec_results)
    logger.info("Report saved: %s", report_path)
    return report_path


def _create_pr(run_id: str, n_patches: int, n_tickets: int) -> None:
    """Commit schema changes on a feature branch and open a GitHub PR."""
    # Refuse to commit directly to main/master
    current = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    if current in ("master", "main"):
        branch = f"notion-eval/{run_id}"
        logger.info("On %s — creating branch %s", current, branch)
        subprocess.run(["git", "checkout", "-b", branch], check=True, timeout=30)
    else:
        branch = current
        logger.info("Using existing branch %s", branch)

    logger.info("Creating PR for %d patches from %d tickets ...", n_patches, n_tickets)
    try:
        subprocess.run(
            [
                "git", "add",
                "schema/concepts.yaml",
                "schema/sql_corrections.yaml",
                "schema/join_edges.csv",
            ],
            check=True, timeout=30,
        )
        msg = f"feat: auto-training patches from {n_tickets} Notion tickets ({run_id})"
        subprocess.run(["git", "commit", "-m", msg], check=True, timeout=30)
        subprocess.run(["git", "push", "-u", "origin", branch], check=True, timeout=120)
        body = (
            f"## Auto-training patches\n\n"
            f"- Run: `{run_id}`\n"
            f"- Branch: `{branch}`\n"
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
            check=True, timeout=60,
        )
        logger.info("PR created successfully.")
    except subprocess.CalledProcessError as exc:
        logger.error("PR creation failed: %s", exc)
    except subprocess.TimeoutExpired as exc:
        logger.error("PR creation timed out: %s", exc)


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
        "--execute", action="store_true",
        help="Execute both SQLs on live DB and compare rowcounts (requires VPN + DATABASE_URL)",
    )
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
    w.add_argument("--execute", action="store_true")
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
            execute=args.execute,
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
                    execute=args.execute,
                )
                seen_ids.update(t.id for t in new_tickets)
            else:
                logger.info("No new tickets. Sleeping %ds ...", args.interval)
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
