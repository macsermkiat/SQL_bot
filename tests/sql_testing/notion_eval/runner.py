"""Cache utility for Notion-based ticket management.

Subcommands:
  fetch  -- show instructions for fetching Notion tickets via MCP
  list   -- show what tickets are in the local cache

Learning from tickets happens interactively in Claude Code sessions:
  1. Read the cache + current schema files
  2. Claude Code proposes generalizations to concepts.yaml / sql_corrections.yaml
  3. Human reviews and applies manually
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from tests.sql_testing.notion_eval.notion_loader import load_tickets, DEFAULT_CACHE_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tests.sql_testing.notion_eval.runner",
        description="Notion ticket cache utility for KCMH SQL bot",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("fetch", help="Show instructions for fetching Notion tickets via MCP")
    sub.add_parser("list", help="Show a summary of tickets in the local cache")

    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.cmd == "fetch":
        print(
            "The 'fetch' subcommand requires the Notion MCP tool.\n"
            "Run it inside a Claude Code session with Notion MCP active,\n"
            "then call: notion_loader.save_cache(tickets)"
        )
        sys.exit(0)

    elif args.cmd == "list":
        if not DEFAULT_CACHE_PATH.exists():
            print(f"No cache found at {DEFAULT_CACHE_PATH}. Run 'fetch' first.")
            sys.exit(1)

        with open(DEFAULT_CACHE_PATH) as f:
            data = json.load(f)

        tickets = load_tickets()
        all_tickets = data.get("tickets", [])

        print(f"\nCache: {DEFAULT_CACHE_PATH}")
        print(f"Total  : {len(all_tickets)}")
        print(f"Usable : {len(tickets)}\n")

        depts: dict[str, int] = {}
        for t in tickets:
            dept = t.department or "—"
            depts[dept] = depts.get(dept, 0) + 1

        print("By department:")
        for dept, count in sorted(depts.items(), key=lambda x: -x[1]):
            print(f"  {dept:<35} {count}")
        print()


if __name__ == "__main__":
    main()
