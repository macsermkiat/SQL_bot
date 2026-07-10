"""
Unit tests for the advisor-tool integration in LLMClient.

The advisor tool (advisor-tool-2026-03-01 beta) lets Sonnet 5 consult
Opus 4.8 mid-generation for strategic guidance on complex SQL generation.

We test:
1. Baseline path (use_advisor=False) is unchanged.
2. Advisor path uses client.beta.messages.create with the beta header
   and advisor tool declaration.
3. JSON is extracted correctly when the response interleaves text
   blocks with server_tool_use and advisor_tool_result blocks.
4. Advisor tokens are captured from usage.iterations and reported
   separately on TokenUsage.
5. Advisor system-prompt guidance starts the volatile block, after the
   stable cached block.
"""

from __future__ import annotations

import os

# Ensure Settings can load without a real API key.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from types import SimpleNamespace  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.llm import LLMClient  # noqa: E402
from app.models import TokenUsage  # noqa: E402

# Clear any cached settings so the env var above takes effect.
get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Helpers to build fake Anthropic responses
# ---------------------------------------------------------------------------


def _fake_block(block_type: str, **fields) -> SimpleNamespace:
    """Build a duck-typed content block (mimics anthropic SDK objects)."""
    return SimpleNamespace(type=block_type, **fields)


def _fake_usage(
    input_tokens: int = 100,
    output_tokens: int = 50,
    iterations: list[dict] | None = None,
) -> SimpleNamespace:
    """Build a duck-typed usage object with optional iterations array."""
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        iterations=iterations or [],
    )


def _fake_response(
    content_blocks: list[SimpleNamespace],
    usage: SimpleNamespace | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        content=content_blocks,
        usage=usage or _fake_usage(),
    )


VALID_SQL_JSON = (
    '{"needs_clarification": false, '
    '"clarification_question": null, '
    '"clarified_question": "count OPD diabetes patients last year", '
    '"assumptions": ["Using ICD10 E10-E14"], '
    '"concepts_used": ["diabetes_icd10"], '
    '"sql": "SELECT COUNT(DISTINCT \\"hn\\") FROM \\"KCMH_HIS\\".\\"PTDIAG\\" '
    'WHERE \\"icd10\\" LIKE \'E1%\'", '
    '"validation_checks": ["range_check"], '
    '"answer_plan": "Report the count with timeframe", '
    '"confidence": "high"}'
)


@pytest.fixture
def llm_client() -> LLMClient:
    """LLMClient with both sync and beta messages mocked."""
    with patch("app.llm.anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        client = LLMClient()
        # Expose the underlying mock for assertions
        client._mock_anthropic = mock_client  # type: ignore[attr-defined]
        yield client


# ---------------------------------------------------------------------------
# 1. Baseline path unchanged
# ---------------------------------------------------------------------------


class TestBaselineUnchanged:
    """use_advisor=False (default) must call the legacy non-beta path."""

    def test_baseline_uses_non_beta_messages_create(
        self, llm_client: LLMClient
    ) -> None:
        mock_messages = llm_client._mock_anthropic.messages  # type: ignore[attr-defined]
        mock_beta_messages = llm_client._mock_anthropic.beta.messages  # type: ignore[attr-defined]

        mock_messages.create.return_value = _fake_response(
            [_fake_block("text", text=f"```json\n{VALID_SQL_JSON}\n```")]
        )

        llm_client.generate_sql(
            user_question="count diabetes patients last year",
            schema_context="schema",
            concepts_context="concepts",
        )

        assert mock_messages.create.called, "baseline path must use messages.create"
        assert not mock_beta_messages.create.called, (
            "baseline path must NOT touch beta.messages.create"
        )

        call_kwargs = mock_messages.create.call_args.kwargs
        assert "tools" not in call_kwargs, "baseline path must not declare tools"
        assert "betas" not in call_kwargs, "baseline path must not set beta header"
        assert call_kwargs["max_tokens"] == 8192
        system = call_kwargs["system"]
        assert isinstance(system, list) and len(system) == 2
        assert system[0]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in system[1]


# ---------------------------------------------------------------------------
# 2. Advisor path: beta header + tool declaration
# ---------------------------------------------------------------------------


class TestAdvisorPathDeclaration:
    def test_advisor_uses_beta_messages_with_correct_header(
        self, llm_client: LLMClient
    ) -> None:
        mock_beta = llm_client._mock_anthropic.beta.messages  # type: ignore[attr-defined]
        mock_beta.create.return_value = _fake_response(
            [_fake_block("text", text=f"```json\n{VALID_SQL_JSON}\n```")]
        )

        llm_client.generate_sql(
            user_question="q",
            schema_context="schema",
            concepts_context="concepts",
            use_advisor=True,
        )

        assert mock_beta.create.called, (
            "advisor path must call client.beta.messages.create"
        )
        kwargs = mock_beta.create.call_args.kwargs

        # Beta header
        assert kwargs.get("betas") == ["advisor-tool-2026-03-01"]

        # Advisor tool declared
        tools = kwargs.get("tools", [])
        advisor_tools = [t for t in tools if t.get("type") == "advisor_20260301"]
        assert len(advisor_tools) == 1, "exactly one advisor tool must be declared"
        advisor = advisor_tools[0]
        assert advisor["name"] == "advisor"
        assert advisor["model"] == "claude-opus-4-8"
        # max_uses should be set (we use a bounded number to control cost)
        assert isinstance(advisor.get("max_uses"), int) and advisor["max_uses"] >= 1

    def test_advisor_system_prompt_includes_timing_guidance(
        self, llm_client: LLMClient
    ) -> None:
        """Advisor timing block must be present so the executor calls the
        advisor before committing to SQL."""
        mock_beta = llm_client._mock_anthropic.beta.messages  # type: ignore[attr-defined]
        mock_beta.create.return_value = _fake_response(
            [_fake_block("text", text=f"```json\n{VALID_SQL_JSON}\n```")]
        )

        llm_client.generate_sql(
            user_question="q",
            schema_context="schema",
            concepts_context="concepts",
            use_advisor=True,
        )

        system_prompt = mock_beta.create.call_args.kwargs["system"]
        assert system_prompt[0]["cache_control"] == {"type": "ephemeral"}
        assert "advisor" in system_prompt[1]["text"].lower()
        assert "advisor" not in system_prompt[0]["text"].lower()
        # Must nudge the executor to consult BEFORE writing SQL
        assert any(
            phrase in system_prompt[1]["text"].lower()
            for phrase in ("before substantive", "before writing", "call advisor")
        )

    def test_codex_guidance_follows_cached_block(
        self, llm_client: LLMClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_messages = llm_client._mock_anthropic.messages  # type: ignore[attr-defined]
        mock_messages.create.return_value = _fake_response(
            [_fake_block("text", text=f"```json\n{VALID_SQL_JSON}\n```")]
        )
        monkeypatch.setattr(llm_client._settings, "advisor_backend", "codex")
        llm_client._openai_client = MagicMock()
        llm_client._openai_client.responses.create.return_value = SimpleNamespace(
            output_text="1. Use OVST and aggregate safely."
        )

        llm_client.generate_sql(
            user_question="q",
            schema_context="schema",
            concepts_context="concepts",
            use_advisor=True,
        )

        system_prompt = mock_messages.create.call_args.kwargs["system"]
        assert system_prompt[0]["cache_control"] == {"type": "ephemeral"}
        assert "CODEX ADVISOR GUIDANCE" not in system_prompt[0]["text"]
        assert system_prompt[1]["text"].startswith("## CODEX ADVISOR GUIDANCE")


# ---------------------------------------------------------------------------
# 3. JSON extraction from interleaved blocks
# ---------------------------------------------------------------------------


class TestJSONExtractionFromInterleavedBlocks:
    """The executor's response may include text blocks around server_tool_use
    and advisor_tool_result. The final JSON usually appears in the last text
    block, so we must concatenate (or prefer the last) text blocks rather
    than grabbing the first one."""

    def test_extracts_json_from_last_text_block_after_advisor_call(
        self, llm_client: LLMClient
    ) -> None:
        mock_beta = llm_client._mock_anthropic.beta.messages  # type: ignore[attr-defined]
        mock_beta.create.return_value = _fake_response(
            [
                _fake_block(
                    "text", text="Let me consult the advisor before writing SQL."
                ),
                _fake_block(
                    "server_tool_use",
                    id="srvtoolu_abc",
                    name="advisor",
                    input={},
                ),
                _fake_block(
                    "advisor_tool_result",
                    tool_use_id="srvtoolu_abc",
                    content=SimpleNamespace(
                        type="advisor_result",
                        text="Join PTDIAG to OVST on vn. Filter by EXTRACT(YEAR ...).",
                    ),
                ),
                _fake_block(
                    "text", text=f"Here is the final query:\n```json\n{VALID_SQL_JSON}\n```"
                ),
            ]
        )

        response, usage = llm_client.generate_sql(
            user_question="q",
            schema_context="schema",
            concepts_context="concepts",
            use_advisor=True,
        )

        assert response.sql.startswith("SELECT COUNT(DISTINCT"), (
            f"expected parsed SQL, got: {response.sql!r}"
        )
        assert response.confidence == "high"
        assert response.needs_clarification is False
        assert usage.input_tokens > 0


# ---------------------------------------------------------------------------
# 4. Advisor token tracking
# ---------------------------------------------------------------------------


class TestAdvisorTokenTracking:
    def test_advisor_tokens_captured_from_iterations(
        self, llm_client: LLMClient
    ) -> None:
        mock_beta = llm_client._mock_anthropic.beta.messages  # type: ignore[attr-defined]
        mock_beta.create.return_value = _fake_response(
            content_blocks=[
                _fake_block("text", text=f"```json\n{VALID_SQL_JSON}\n```"),
            ],
            usage=_fake_usage(
                input_tokens=412,
                output_tokens=531,
                iterations=[
                    {
                        "type": "message",
                        "input_tokens": 412,
                        "output_tokens": 89,
                    },
                    {
                        "type": "advisor_message",
                        "model": "claude-opus-4-8",
                        "input_tokens": 823,
                        "output_tokens": 1612,
                    },
                    {
                        "type": "message",
                        "input_tokens": 1348,
                        "output_tokens": 442,
                    },
                ],
            ),
        )

        _, usage = llm_client.generate_sql(
            user_question="q",
            schema_context="schema",
            concepts_context="concepts",
            use_advisor=True,
        )

        assert isinstance(usage, TokenUsage)
        # Executor totals come from the top-level usage fields.
        assert usage.input_tokens == 412
        assert usage.output_tokens == 531
        # Advisor tokens are tracked separately (NOT rolled into exec totals).
        assert usage.advisor_input_tokens == 823
        assert usage.advisor_output_tokens == 1612

    def test_advisor_tokens_default_to_zero_without_iterations(
        self, llm_client: LLMClient
    ) -> None:
        """Baseline / no-advisor path never populates iterations."""
        mock_messages = llm_client._mock_anthropic.messages  # type: ignore[attr-defined]
        mock_messages.create.return_value = _fake_response(
            [_fake_block("text", text=f"```json\n{VALID_SQL_JSON}\n```")]
        )

        _, usage = llm_client.generate_sql(
            user_question="q",
            schema_context="schema",
            concepts_context="concepts",
        )

        assert usage.advisor_input_tokens == 0
        assert usage.advisor_output_tokens == 0


class TestSonnetFiveConfiguration:
    def test_clients_receive_explicit_timeouts(self) -> None:
        settings = SimpleNamespace(
            anthropic_api_key="anthropic-test-key",
            claude_model="claude-sonnet-5",
            openai_api_key="openai-test-key",
        )
        with (
            patch("app.llm.get_settings", return_value=settings),
            patch("app.llm.anthropic.Anthropic") as anthropic_client,
            patch("app.llm.openai.OpenAI") as openai_client,
        ):
            LLMClient()

        anthropic_client.assert_called_once_with(
            api_key="anthropic-test-key",
            timeout=120.0,
            max_retries=1,
        )
        openai_client.assert_called_once_with(
            api_key="openai-test-key",
            timeout=60.0,
        )

    def test_extended_thinking_uses_adaptive_and_safe_fallback(
        self, llm_client: LLMClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_messages = llm_client._mock_anthropic.messages  # type: ignore[attr-defined]
        mock_messages.create.side_effect = [
            RuntimeError("adaptive unavailable"),
            _fake_response(
                [_fake_block("text", text=f"```json\n{VALID_SQL_JSON}\n```")]
            ),
        ]

        with caplog.at_level("WARNING", logger="app.llm"):
            llm_client.generate_sql(
                user_question="q",
                schema_context="schema",
                concepts_context="concepts",
                extended_thinking=True,
            )

        first_call, fallback_call = mock_messages.create.call_args_list
        assert first_call.kwargs["thinking"] == {"type": "adaptive"}
        assert first_call.kwargs["max_tokens"] == 16000
        assert fallback_call.kwargs["thinking"] == {"type": "disabled"}
        assert fallback_call.kwargs["max_tokens"] == 8192
        assert "claude-sonnet-5" in caplog.text
        assert "adaptive unavailable" in caplog.text

    def test_format_answer_disables_thinking_and_extracts_final_text(
        self, llm_client: LLMClient
    ) -> None:
        mock_messages = llm_client._mock_anthropic.messages  # type: ignore[attr-defined]
        mock_messages.create.return_value = _fake_response([
            _fake_block("thinking", thinking="internal reasoning"),
            _fake_block("text", text="Formatted answer"),
        ])

        answer, _ = llm_client.format_answer(
            question="q",
            _sql="SELECT 1",
            result_data={"columns": ["n"], "rows": [[1]], "row_count": 1},
            assumptions=[],
            concepts_used=[],
        )

        kwargs = mock_messages.create.call_args.kwargs
        assert kwargs["thinking"] == {"type": "disabled"}
        assert kwargs["max_tokens"] == 2048
        assert answer == "Formatted answer"
