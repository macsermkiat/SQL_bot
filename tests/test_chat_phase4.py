"""Tests for the unified chat pipeline and DB-error sanitization."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.chat import (
    STANDARD_QUERY_ERROR,
    ChatOrchestrator,
    _sanitize_db_error,
)
from app.models import ChatRequest, ChatResponse, TokenUsage


def test_sanitize_db_error_strips_literal_values():
    error = (
        "invalid input syntax for type date: \"patient-value\"; "
        "value 'PII value'"
    )

    sanitized = _sanitize_db_error(error)

    assert "patient-value" not in sanitized
    assert "PII value" not in sanitized
    assert sanitized.count("[REDACTED]") == 2


def test_sanitize_db_error_keeps_quoted_identifier():
    error = 'column "x" does not exist in relation "visits"'

    assert _sanitize_db_error(error) == error


@pytest.mark.asyncio
async def test_retry_context_uses_sanitized_error(monkeypatch: pytest.MonkeyPatch):
    orchestrator = ChatOrchestrator()
    orchestrator._catalog = MagicMock(tables={})
    generator = MagicMock()
    generator.generate.return_value = (None, None)
    monkeypatch.setattr("app.chat.get_sql_generator", lambda: generator)
    monkeypatch.setattr(
        "app.chat.get_learning_store",
        lambda: MagicMock(build_prompt_section=lambda *args, **kwargs: ""),
    )

    orchestrator._retry_with_accumulated_errors(
        "question",
        [{
            "sql": "SELECT 1",
            "error": 'column "x" does not exist; bad value \'PII value\'',
            "stage": "execution",
        }],
        [],
    )

    history = generator.generate.call_args.kwargs["conversation_history"]
    prompt = "\n".join(message["content"] for message in history)
    assert 'column "x" does not exist' in prompt
    assert "PII value" not in prompt
    assert "[REDACTED]" in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_role", "expected_answer", "expected_error"),
    [
        ("standard_user", STANDARD_QUERY_ERROR, STANDARD_QUERY_ERROR),
        ("super_user", "Raw validation detail", "secret DB detail"),
    ],
)
async def test_handle_message_consumes_terminal_stream_event(
    monkeypatch: pytest.MonkeyPatch,
    user_role: str,
    expected_answer: str,
    expected_error: str,
):
    orchestrator = ChatOrchestrator()
    session = SimpleNamespace(session_id="session-1")
    session_manager = MagicMock()
    session_manager.get_or_create_session.return_value = session
    monkeypatch.setattr("app.chat.get_session_manager", lambda: session_manager)
    monkeypatch.setattr("app.chat.get_db", lambda: MagicMock())

    async def fake_streaming(*args, **kwargs):
        yield {"event": "progress", "progress": 50}
        yield {
            "event": "complete",
            "data": ChatResponse(
                session_id="session-1",
                answer="Raw validation detail",
                error="secret DB detail",
            ).model_dump(),
        }

    monkeypatch.setattr(orchestrator, "handle_message_streaming", fake_streaming)

    response = await orchestrator.handle_message(
        ChatRequest(message="question", session_id="session-1"),
        user_email="user@hospital.org",
        user_role=user_role,
    )

    assert response.answer == expected_answer
    assert response.error == expected_error


@pytest.mark.asyncio
async def test_streaming_failure_is_generic_for_standard_user(
    monkeypatch: pytest.MonkeyPatch,
):
    orchestrator = ChatOrchestrator()
    generator = MagicMock()
    generator.generate.return_value = (
        SimpleNamespace(
            needs_clarification=False,
            sql="",
            assumptions=[],
            concepts_used=[],
            confidence="low",
        ),
        TokenUsage(),
    )
    session_manager = MagicMock()
    session_manager.get_conversation_history.return_value = []
    cancellable = MagicMock()
    monkeypatch.setattr("app.chat.get_sql_generator", lambda: generator)
    monkeypatch.setattr("app.chat.get_session_manager", lambda: session_manager)
    monkeypatch.setattr("app.chat.create_log_task", lambda log: None)

    events = [
        event
        async for event in orchestrator._process_question_streaming(
            question="question",
            session_id="session-1",
            cancellable=cancellable,
            user_role="standard_user",
        )
    ]

    terminal = events[-1]["data"]
    assert terminal["answer"] == STANDARD_QUERY_ERROR
    assert terminal["error"] == STANDARD_QUERY_ERROR
    assert "No SQL generated" not in terminal["answer"]
