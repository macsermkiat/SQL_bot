"""
Query attempt logging — local JSONL file (always) + Supabase REST (when reachable).

Each call to create_log_task() schedules a background asyncio task that:
1. Appends the log entry to a local JSONL file (never fails)
2. POSTs the row to Supabase (fire-and-forget, silently fails if network blocked)

Use `python -m app.query_logger sync` to push unsynced local logs to Supabase.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None

# Local log file path (next to app/)
_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_FILE = _LOG_DIR / "query_logs.jsonl"
_SYNCED_FILE = _LOG_DIR / "query_logs_synced.jsonl"


def _get_client() -> httpx.AsyncClient:
    """Return module-level httpx client (created once)."""
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.supabase_url or not settings.supabase_service_key:
            raise RuntimeError("Supabase not configured")
        is_tunnel = "localhost" in settings.supabase_url or "127.0.0.1" in settings.supabase_url
        _client = httpx.AsyncClient(
            base_url=settings.supabase_url,
            headers={
                "apikey": settings.supabase_service_key,
                "Authorization": f"Bearer {settings.supabase_service_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            timeout=15.0,
            verify=not is_tunnel,
        )
    return _client


@dataclasses.dataclass
class AttemptLog:
    """One row in the query_logs table."""

    query_group_id: UUID
    attempt_number: int
    session_id: str
    question: str
    attempt_stage: str
    user_email: str | None = None
    user_role: str | None = None
    generated_sql: str | None = None
    assumptions: list[str] | None = None
    concepts_used: list[str] | None = None
    confidence: str | None = None
    llm_raw_response: str | None = None
    guard_valid: bool | None = None
    guard_error: str | None = None
    explain_valid: bool | None = None
    explain_error: str | None = None
    execution_time_ms: float | None = None
    row_count: int | None = None
    result_truncated: bool | None = None
    error_message: str | None = None
    answer: str | None = None
    sanity_checks: list[dict[str, Any]] | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


def _serialise(log: AttemptLog) -> dict[str, Any]:
    """Convert AttemptLog to a JSON-serializable dict."""
    return {
        "query_group_id": str(log.query_group_id),
        "attempt_number": log.attempt_number,
        "session_id": log.session_id,
        "user_email": log.user_email,
        "user_role": log.user_role,
        "question": log.question,
        "generated_sql": log.generated_sql,
        "assumptions": log.assumptions,
        "concepts_used": log.concepts_used,
        "confidence": log.confidence,
        "llm_raw_response": log.llm_raw_response,
        "guard_valid": log.guard_valid,
        "guard_error": log.guard_error,
        "explain_valid": log.explain_valid,
        "explain_error": log.explain_error,
        "execution_time_ms": log.execution_time_ms,
        "row_count": log.row_count,
        "result_truncated": log.result_truncated,
        "attempt_stage": log.attempt_stage,
        "error_message": log.error_message,
        "answer": log.answer,
        "sanity_checks": log.sanity_checks,
        "input_tokens": log.input_tokens,
        "output_tokens": log.output_tokens,
        "total_tokens": log.total_tokens,
    }


def _write_local(payload: dict[str, Any]) -> None:
    """Append one JSON line to local log file. Always succeeds."""
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        row = {**payload, "created_at": datetime.now(timezone.utc).isoformat(), "synced": False}
        with _LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        logger.warning("query_logger: failed to write local log", exc_info=True)


async def _post_supabase(payload: dict[str, Any]) -> bool:
    """POST one row to Supabase. Returns True on success."""
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_key:
        return False
    try:
        client = _get_client()
        response = await client.post("/rest/v1/query_logs", json=payload)
        if response.status_code in (200, 201):
            return True
        logger.warning(
            "query_logger: Supabase insert failed %d - %s",
            response.status_code,
            response.text[:200],
        )
    except Exception:
        logger.debug("query_logger: Supabase unreachable (network blocked?)")
    return False


async def log_attempt(log: AttemptLog) -> None:
    """Log one attempt: local file (always) + Supabase (best-effort)."""
    payload = _serialise(log)
    _write_local(payload)
    await _post_supabase(payload)


def create_log_task(log: AttemptLog) -> None:
    """Schedule log_attempt as a fire-and-forget asyncio task."""
    try:
        asyncio.get_running_loop().create_task(
            log_attempt(log),
            name=f"query_log_{log.query_group_id}_{log.attempt_number}",
        )
    except RuntimeError:
        # No event loop (e.g. tests) — write local only
        payload = _serialise(log)
        _write_local(payload)


# ---------------------------------------------------------------------------
# CLI: python -m app.query_logger sync
# Push unsynced local logs to Supabase from an unrestricted network
# ---------------------------------------------------------------------------

def sync_to_supabase() -> None:
    """Read local JSONL, push unsynced rows to Supabase, mark as synced."""
    import sys

    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_key:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        sys.exit(1)

    if not _LOG_FILE.exists():
        print(f"No local logs found at {_LOG_FILE}")
        return

    lines = _LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
    unsynced = []
    already_synced = []

    for line in lines:
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("synced"):
            already_synced.append(row)
        else:
            unsynced.append(row)

    if not unsynced:
        print(f"All {len(already_synced)} rows already synced.")
        return

    print(f"Found {len(unsynced)} unsynced rows (of {len(lines)} total).")

    is_tunnel = "localhost" in settings.supabase_url or "127.0.0.1" in settings.supabase_url
    client = httpx.Client(
        base_url=settings.supabase_url,
        headers={
            "apikey": settings.supabase_service_key,
            "Authorization": f"Bearer {settings.supabase_service_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        timeout=15.0,
        verify=not is_tunnel,
    )

    success_count = 0
    failed = []

    for row in unsynced:
        # Remove local-only fields before posting
        payload = {k: v for k, v in row.items() if k not in ("synced", "created_at")}
        try:
            resp = client.post("/rest/v1/query_logs", json=payload)
            if resp.status_code in (200, 201):
                row["synced"] = True
                success_count += 1
            else:
                print(f"  Failed ({resp.status_code}): {resp.text[:100]}")
                failed.append(row)
        except Exception as e:
            print(f"  Error: {e}")
            failed.append(row)

    # Rewrite the file with updated sync status
    all_rows = already_synced + [r for r in unsynced if r.get("synced")] + failed
    with _LOG_FILE.open("w", encoding="utf-8") as f:
        for row in all_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Synced {success_count}/{len(unsynced)} rows. {len(failed)} failed.")
    client.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "sync":
        sync_to_supabase()
    else:
        print("Usage: python -m app.query_logger sync")
        print("  Push unsynced local logs to Supabase")
