"""Load Notion tickets from local cache or live Notion MCP."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from tests.sql_testing.notion_eval.ticket_models import TicketData

logger = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "test_data"
    / "notion_eval"
    / "tickets_cache.json"
)

COLLECTION_URL = "collection://1f198331-76c8-80da-8634-000b89ff0491"


def load_tickets(cache_path: Path | None = None) -> list[TicketData]:
    """Load usable tickets from the local cache file."""
    path = cache_path or DEFAULT_CACHE_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Tickets cache not found: {path}\n"
            "Run 'python -m tests.sql_testing.notion_eval.runner fetch' to populate it."
        )

    with open(path) as f:
        data = json.load(f)

    tickets = [TicketData.from_dict(t) for t in data.get("tickets", [])]
    usable = [t for t in tickets if t.is_usable()]
    logger.info(
        "Loaded %d tickets from cache (%d usable, %d skipped)",
        len(tickets),
        len(usable),
        len(tickets) - len(usable),
    )
    return usable


def load_all_ticket_ids(cache_path: Path | None = None) -> set[str]:
    """Return all Notion page IDs in the cache (including unusable ones)."""
    path = cache_path or DEFAULT_CACHE_PATH
    if not path.exists():
        return set()
    with open(path) as f:
        data = json.load(f)
    return {t["id"] for t in data.get("tickets", [])}


def save_cache(tickets: list[TicketData], cache_path: Path | None = None) -> None:
    """Merge new tickets into the local cache file."""
    path = cache_path or DEFAULT_CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: list[dict] = []
    if path.exists():
        with open(path) as f:
            existing_data = json.load(f)
        existing = existing_data.get("tickets", [])

    existing_ids = {t["id"] for t in existing}
    new_entries = [t.to_dict() for t in tickets if t.id not in existing_ids]

    all_tickets = existing + new_entries
    payload = {
        "version": "1",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "notion_mcp",
        "collection_url": COLLECTION_URL,
        "tickets": all_tickets,
    }

    with open(path, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    logger.info(
        "Cache updated: %d existing + %d new = %d total tickets",
        len(existing),
        len(new_entries),
        len(all_tickets),
    )
