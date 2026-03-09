"""
Fire-and-forget query attempt logging to Supabase REST API.

Each call to create_log_task() schedules a background asyncio task that
POSTs one row to the Supabase query_logs table. It never blocks the caller.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from typing import Any
from uuid import UUID

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Return module-level httpx client (created once)."""
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.supabase_url or not settings.supabase_service_key:
            raise RuntimeError("Supabase not configured")
        # When tunneling via SSH reverse port forward (e.g. localhost:8443),
        # TLS cert won't match — disable verification for the tunnel only
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
    """Convert AttemptLog to the Supabase REST row dict."""
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


async def log_attempt(log: AttemptLog) -> None:
    """POST one attempt row to Supabase. Called as a background task."""
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_key:
        return
    try:
        client = _get_client()
        payload = _serialise(log)
        response = await client.post("/rest/v1/query_logs", json=payload)
        if response.status_code not in (200, 201):
            logger.warning(
                "query_logger: Supabase insert failed %d - %s",
                response.status_code,
                response.text[:200],
            )
    except Exception:
        logger.warning("query_logger: failed to log attempt", exc_info=True)


def create_log_task(log: AttemptLog) -> None:
    """Schedule log_attempt as a fire-and-forget asyncio task."""
    try:
        asyncio.get_running_loop().create_task(
            log_attempt(log),
            name=f"query_log_{log.query_group_id}_{log.attempt_number}",
        )
    except RuntimeError:
        logger.debug("query_logger: no running event loop, skipping log")
