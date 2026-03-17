"""
Notion logger -- push completed query logs to a Notion database (fire-and-forget).

Each successful query attempt (attempt_stage == "answer") creates one row
in the configured Notion database, mirroring the fields stored in Supabase.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_NOTION_API_URL = "https://api.notion.com/v1/pages"
_NOTION_VERSION = "2022-06-28"
_MAX_TEXT_LENGTH = 2000  # Notion rich_text property limit

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Return module-level httpx client for Notion API (created once)."""
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.notion_api_key:
            raise RuntimeError("Notion API key not configured")
        _client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {settings.notion_api_key}",
                "Content-Type": "application/json",
                "Notion-Version": _NOTION_VERSION,
            },
            timeout=15.0,
        )
    return _client


def _truncate(text: str | None, limit: int = _MAX_TEXT_LENGTH) -> str:
    """Truncate text to Notion's rich_text limit."""
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _build_properties(payload: dict[str, Any]) -> dict[str, Any]:
    """Map a serialised AttemptLog payload to Notion page properties."""
    props: dict[str, Any] = {}

    # Title property -- "Output" is the title column
    question = payload.get("question") or "Untitled query"
    props["Output"] = {
        "title": [{"text": {"content": _truncate(question)}}],
    }

    # Rich text fields
    text_mappings = {
        "Session ID": "session_id",
        "Query Group ID": "query_group_id",
        "Generated SQL": "generated_sql",
        "Answer": "answer",
        "Error Message": "error_message",
        "Data Request": "question",
    }
    for notion_prop, log_field in text_mappings.items():
        value = payload.get(log_field)
        if value is not None:
            props[notion_prop] = {
                "rich_text": [{"text": {"content": _truncate(str(value))}}],
            }

    # Assumptions (list -> JSON string)
    assumptions = payload.get("assumptions")
    if assumptions:
        text = json.dumps(assumptions, ensure_ascii=False)
        props["Assumptions"] = {
            "rich_text": [{"text": {"content": _truncate(text)}}],
        }

    # Email field (validate before sending -- Notion rejects invalid emails)
    email = payload.get("user_email")
    if email and isinstance(email, str) and "@" in email:
        props["User's Email"] = {"email": email}

    # Select fields
    role = payload.get("user_role")
    if role in ("super_user", "standard_user"):
        props["User Role"] = {"select": {"name": role}}

    confidence = payload.get("confidence")
    if confidence in ("high", "medium", "low"):
        props["Confidence"] = {"select": {"name": confidence}}

    # Multi-select (concepts_used)
    concepts = payload.get("concepts_used")
    if concepts and isinstance(concepts, list):
        props["Concepts Used"] = {
            "multi_select": [{"name": c[:100]} for c in concepts[:25]],
        }

    # Checkbox fields
    guard_valid = payload.get("guard_valid")
    if guard_valid is not None:
        props["Guard Valid"] = {"checkbox": bool(guard_valid)}

    explain_valid = payload.get("explain_valid")
    if explain_valid is not None:
        props["Explain Valid"] = {"checkbox": bool(explain_valid)}

    # Number fields
    number_mappings = {
        "Attempt Number": "attempt_number",
        "Execution Time (ms)": "execution_time_ms",
        "Row Count": "row_count",
        "Input Tokens": "input_tokens",
        "Output Tokens": "output_tokens",
        "Total Tokens": "total_tokens",
    }
    for notion_prop, log_field in number_mappings.items():
        value = payload.get(log_field)
        if value is not None:
            try:
                props[notion_prop] = {"number": float(value)}
            except (TypeError, ValueError):
                pass

    return props


async def post_to_notion(payload: dict[str, Any]) -> bool:
    """Create one page in the Notion database. Returns True on success."""
    settings = get_settings()
    if not settings.notion_api_key or not settings.notion_database_id:
        return False

    try:
        client = _get_client()
        body = {
            "parent": {"database_id": settings.notion_database_id},
            "properties": _build_properties(payload),
        }
        response = await client.post(_NOTION_API_URL, json=body)
        if response.status_code in (200, 201):
            return True
        logger.warning(
            "notion_logger: Notion insert failed %d - %s",
            response.status_code,
            response.text[:300],
        )
    except Exception:
        logger.warning("notion_logger: Notion API request failed", exc_info=True)
    return False
