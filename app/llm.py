"""
Claude API wrapper for SQL generation.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic
import openai

from app.config import get_settings
from app.models import SQLGenerationResponse, TokenUsage


logger = logging.getLogger(__name__)


# Beta header required for the advisor tool.
ADVISOR_BETA_HEADER = "advisor-tool-2026-03-01"
ADVISOR_TOOL_TYPE = "advisor_20260301"

# Added to the volatile system block when the Anthropic advisor tool is enabled.
# Adapted from the official guidance at
# https://platform.claude.com/docs/en/docs/agents-and-tools/tool-use/advisor-tool
ADVISOR_SYSTEM_GUIDANCE = """You have access to an `advisor` tool backed by a stronger reviewer model (Opus). \
It takes NO parameters — when you call advisor(), your entire conversation history is automatically forwarded. \
The advisor sees the question, schema context, concepts, and every prior reasoning step.

Call advisor BEFORE writing the final SQL — before committing to a table choice, join pattern, or filter \
interpretation. Orientation (reading schema, thinking about which concepts apply) is not substantive work. \
Writing the SQL and declaring done ARE substantive work.

Also call advisor:
- When the question is ambiguous and a wrong concept mapping would produce a silently-wrong answer.
- When the required join path spans 3+ tables or involves header/detail relationships.
- When you are uncertain which ICD/drug/lab code pattern matches the user's intent.

Give the advice serious weight. If you follow a step and it conflicts with a schema constraint you can verify \
(column does not exist, PHI block, type mismatch), adapt — but surface the conflict to the advisor on a second \
call rather than silently switching.

The advisor should respond in under 100 words, using enumerated steps, not explanations.

"""

# Template added to the volatile system block when Codex advisor guidance is injected.
CODEX_ADVISOR_GUIDANCE_HEADER = """## CODEX ADVISOR GUIDANCE (from OpenAI {model})
An external OpenAI model reviewed this task before you. Follow the numbered steps below closely.
If any step conflicts with a verified schema constraint, adapt and note the deviation.

{guidance}

---
"""


class LLMClient:
    """Claude API client for SQL generation."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=120.0,
            max_retries=1,
        )
        self._model = settings.claude_model
        self._settings = settings
        self._openai_client: openai.OpenAI | None = (
            openai.OpenAI(api_key=settings.openai_api_key, timeout=60.0)
            if settings.openai_api_key
            else None
        )

    def generate_sql(
        self,
        user_question: str,
        schema_context: str,
        concepts_context: str,
        conversation_history: list[dict[str, str]] | None = None,
        extended_thinking: bool = False,
        use_advisor: bool = False,
    ) -> tuple[SQLGenerationResponse, TokenUsage]:
        """
        Generate SQL from natural language question.

        Args:
            user_question: User's analytical question
            schema_context: Schema information (tables, columns)
            concepts_context: Clinical concept definitions
            conversation_history: Previous messages for context
            extended_thinking: Enable extended thinking for harder reasoning
            use_advisor: If True, use the advisor tool (beta) so the executor
                can consult a stronger advisor model mid-generation.
                Mutually exclusive with extended_thinking.

        Returns:
            Tuple of (SQLGenerationResponse, TokenUsage)
        """
        system_prompt = self._build_system_prompt(schema_context, concepts_context)

        if use_advisor and self._settings.advisor_backend == "codex":
            guidance = self._call_codex_advisor(schema_context, concepts_context, user_question)
            system_prompt[1]["text"] = (
                CODEX_ADVISOR_GUIDANCE_HEADER.format(
                    model=self._settings.codex_model,
                    guidance=guidance,
                )
                + system_prompt[1]["text"]
            )
        elif use_advisor:
            system_prompt[1]["text"] = (
                ADVISOR_SYSTEM_GUIDANCE + system_prompt[1]["text"]
            )

        messages = self._build_messages(user_question, conversation_history)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 16000 if extended_thinking else 8192,
            "system": system_prompt,
            "messages": messages,
        }

        if extended_thinking and not use_advisor:
            kwargs["thinking"] = {"type": "adaptive"}

        if use_advisor and self._settings.advisor_backend == "anthropic":
            response = self._create_with_advisor(kwargs)
        else:
            try:
                response = self._client.messages.create(**kwargs)
            except Exception as exc:
                if extended_thinking:
                    logger.warning(
                        "Adaptive thinking failed for model %s; retrying with "
                        "thinking disabled: %s",
                        self._model,
                        exc,
                    )
                    kwargs["thinking"] = {"type": "disabled"}
                    kwargs["max_tokens"] = 8192
                    response = self._client.messages.create(**kwargs)
                else:
                    raise

        usage = self._extract_usage(response)
        text_content = self._extract_final_text(response.content)
        return self._parse_response(text_content), usage

    # ------------------------------------------------------------------
    # Advisor helpers
    # ------------------------------------------------------------------

    def _create_with_advisor(self, kwargs: dict[str, Any]) -> Any:
        """Invoke the beta messages endpoint with the advisor tool declared."""
        kwargs = {
            **kwargs,
            "betas": [ADVISOR_BETA_HEADER],
            "tools": [
                {
                    "type": ADVISOR_TOOL_TYPE,
                    "name": "advisor",
                    "model": self._settings.advisor_model,
                    "max_uses": self._settings.advisor_max_uses,
                }
            ],
        }
        return self._client.beta.messages.create(**kwargs)

    def _call_codex_advisor(
        self,
        schema_context: str,
        concepts_context: str,
        user_question: str,
    ) -> str:
        """Call OpenAI Codex (GPT-5.5) for pre-generation advisory guidance.

        Returns enumerated steps (≤100 words) that are injected into Claude's
        system prompt before SQL generation begins.
        """
        if self._openai_client is None:
            raise ValueError(
                "advisor_backend='codex' requires OPENAI_API_KEY to be set in .env"
            )

        advisor_prompt = f"""You are a SQL review advisor for KCMH hospital information system (PostgreSQL).

Analyse this SQL generation task and respond with numbered steps only (max 100 words).

Question: {user_question}

Schema summary (truncated):
{schema_context[:2500]}

Clinical concepts available:
{concepts_context[:500]}

Advise on:
1. Most likely correct tables and join path
2. PHI columns to exclude from SELECT output (hn, cid, fname, lname, dob, etc.)
3. Key ambiguities and safe assumptions
4. ICD/drug/lab code patterns if relevant

Numbered steps only. No explanations. Under 100 words."""

        response = self._openai_client.responses.create(
            model=self._settings.codex_model,
            input=advisor_prompt,
        )
        return response.output_text

    @staticmethod
    def _extract_final_text(content_blocks: list[Any]) -> str:
        """Return the last text block's text (where the final JSON lives).

        With the advisor tool, the executor may emit an intermediate text
        block ("Let me consult the advisor..."), then a server_tool_use +
        advisor_tool_result pair, then the final answer in another text
        block. The final SQL/JSON is in the last text block.
        """
        last_text = ""
        for block in content_blocks:
            if getattr(block, "type", None) == "text":
                last_text = getattr(block, "text", "") or last_text
        return last_text

    @staticmethod
    def _extract_usage(response: Any) -> TokenUsage:
        """Build TokenUsage, splitting executor and advisor sub-inference."""
        usage = response.usage
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0

        advisor_in = 0
        advisor_out = 0
        iterations = getattr(usage, "iterations", None) or []
        for it in iterations:
            # iterations entries may be dicts or objects
            it_type = it.get("type") if isinstance(it, dict) else getattr(it, "type", None)
            if it_type == "advisor_message":
                get = it.get if isinstance(it, dict) else lambda k, _d=it: getattr(_d, k, 0)
                advisor_in += get("input_tokens", 0) or 0
                advisor_out += get("output_tokens", 0) or 0

        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            advisor_input_tokens=advisor_in,
            advisor_output_tokens=advisor_out,
        )

    def _build_system_prompt(
        self,
        schema_context: str,
        concepts_context: str,
    ) -> list[dict[str, Any]]:
        """Build stable cached and volatile system prompt blocks.

        Lean prompt: only universal rules that apply to every query.
        Domain knowledge (drugs, procedures, vitals, routing) lives in
        concepts.yaml and is injected via {concepts_context}.
        """
        from datetime import datetime
        import zoneinfo

        bangkok_tz = zoneinfo.ZoneInfo("Asia/Bangkok")
        now = datetime.now(bangkok_tz)
        current_date = now.strftime("%Y-%m-%d")
        current_year = now.year
        last_year = current_year - 1

        stable_prompt = f"""You are a SQL expert for KCMH HIS. Convert questions to safe, read-only PostgreSQL.

## SAFETY RULES
1. SELECT only. No INSERT/UPDATE/DELETE/DROP/CREATE/ALTER.
2. NO PHI in SELECT output: hn, cid, fname, lname, name, phone, address, dob, passport, mrn, email. OK in JOIN/WHERE only.
3. Aggregate by default (COUNT/SUM/AVG). Non-aggregate needs LIMIT (max 2000).
4. No SELECT *. Explicit columns only. Date-filter large tables.
5. If user asks for patient-identifying data, REFUSE: set needs_clarification=true, offer aggregate alternative.

## POSTGRESQL SYNTAX
- Schema "KCMH_HIS". Double-quote all identifiers: "KCMH_HIS"."TABLE"."col"
- WRONG: SELECT vn FROM OVST | RIGHT: SELECT "vn" FROM "KCMH_HIS"."OVST"
- LIMIT not TOP. EXTRACT(YEAR FROM col) not YEAR(). Dates: 'YYYY-MM-DD'.

## DATA TYPES
Schema marks: n=numeric, t=text, d=date, b=bool. Match literals to types:
- Numeric cols: WHERE x IN (1,2) not ('A','B'). LIKE only on text cols.
- Use IS NULL not =NULL. LOWER() for case-insensitive text. Status codes are often numeric.
- NEVER fabricate or hardcode meditem/ICD codes in VALUES clauses. Always query reference tables dynamically.

## TABLE-SCHEMA GUIDANCE
Two sections: TABLE DIRECTORY (all tables, compact) + DETAILED SCHEMA (columns for selected tables).
- Prefer [DETAILED] tables. Non-detailed can use universal keys (hn/vn/an).
- Do NOT invent tables. Heed ! warnings for common column mistakes.
- Aliases: never use "lvst" for LVSTEXM, "pt" for PTDIAG, "dct" for DCTSPEC.
- Detail tables may lack hn/vn/an. Check "Header-Detail Join Rules" in schema context for required JOINs.

## PERFORMANCE
- Pre-filter ref tables in CTEs, INNER JOIN to transaction tables.
- EXISTS not JOIN for COUNT(DISTINCT) across tables.
- Cross-year: single scan + EXTRACT(YEAR FROM date), never scan same table twice.
- Numeric text (lab results): CASE WHEN col ~ '^[0-9]+(\\.[0-9]+)?$' THEN CAST(col AS NUMERIC) END

## CONCEPTS (domain knowledge - ALWAYS check before writing SQL)
{concepts_context}

## KEYS
- hn: patient ID (PHI, JOIN only) | an: inpatient admission | vn: outpatient visit

## OUTPUT (JSON only)
```json
{{{{"needs_clarification":false,"clarification_question":null,"clarified_question":"...","assumptions":["..."],"concepts_used":["..."],"sql":"SELECT ...","validation_checks":["..."],"answer_plan":"...","confidence":"high|medium|low"}}}}
```
If unsure about table/column, set needs_clarification=true.
"""

        volatile_prompt = f"""## TABLE SCHEMA
{schema_context}

## DATES
Today: {current_date} | Year: {current_year} | Last year: {last_year}
"""

        return [
            {
                "type": "text",
                "text": stable_prompt,
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text", "text": volatile_prompt},
        ]

    def _build_messages(
        self,
        user_question: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> list[dict[str, Any]]:
        """Build messages array for API call."""
        messages = []

        # Add conversation history if provided
        if conversation_history:
            for msg in conversation_history[-6:]:  # Keep last 6 messages for context
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"],
                })

        # Add current question
        messages.append({
            "role": "user",
            "content": f"Question: {user_question}\n\nGenerate SQL and respond with JSON only.",
        })

        return messages

    def _parse_response(self, response_text: str) -> SQLGenerationResponse:
        """Parse LLM response into structured object."""
        # Try to extract JSON from response
        try:
            # Handle markdown code blocks
            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                json_str = response_text[start:end].strip()
            elif "```" in response_text:
                start = response_text.find("```") + 3
                end = response_text.find("```", start)
                json_str = response_text[start:end].strip()
            else:
                json_str = response_text.strip()

            data = json.loads(json_str)
            return SQLGenerationResponse(**data)
        except (json.JSONDecodeError, ValueError) as e:
            # If parsing fails, return error response
            return SQLGenerationResponse(
                needs_clarification=True,
                clarification_question=f"I had trouble understanding the request. Could you rephrase it? (Error: {e})",
                confidence="low",
            )

    def format_answer(
        self,
        question: str,
        _sql: str,
        result_data: dict[str, Any],
        assumptions: list[str],
        concepts_used: list[str],
    ) -> tuple[str, TokenUsage]:
        """
        Format the final answer from query results.

        Args:
            question: Original user question
            _sql: Executed SQL (unused in formatting, kept for API compatibility)
            result_data: Query results
            assumptions: Assumptions made
            concepts_used: Concepts used

        Returns:
            Tuple of (answer text, TokenUsage)
        """
        messages = [{
            "role": "user",
            "content": f"""Given this question: {question}

And this SQL result:
Columns: {result_data.get('columns', [])}
Rows: {result_data.get('rows', [])[:20]}  # First 20 rows
Total rows: {result_data.get('row_count', 0)}
Truncated: {result_data.get('truncated', False)}

Assumptions made: {assumptions}
Concepts used: {concepts_used}

Provide a clear, concise answer in the user's language (Thai if question is Thai, otherwise English).
Include:
1. Direct answer with numbers
2. Timeframe and definitions used
3. Any important caveats

Keep it brief and professional.""",
        }]

        response = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            thinking={"type": "disabled"},
            messages=messages,
        )

        usage = TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
        )

        return self._extract_final_text(response.content), usage


# Global client instance
_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get global LLM client instance."""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
