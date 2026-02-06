"""
Claude API wrapper for SQL generation.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from app.config import get_settings
from app.models import SQLGenerationResponse


class LLMClient:
    """Claude API client for SQL generation."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.claude_model

    def generate_sql(
        self,
        user_question: str,
        schema_context: str,
        concepts_context: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> SQLGenerationResponse:
        """
        Generate SQL from natural language question.

        Args:
            user_question: User's analytical question
            schema_context: Schema information (tables, columns)
            concepts_context: Clinical concept definitions
            conversation_history: Previous messages for context

        Returns:
            SQLGenerationResponse with SQL and metadata
        """
        system_prompt = self._build_system_prompt(schema_context, concepts_context)
        messages = self._build_messages(user_question, conversation_history)

        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
        )

        return self._parse_response(response.content[0].text)

    def _build_system_prompt(self, schema_context: str, concepts_context: str) -> str:
        """Build the system prompt with schema and concept context."""
        from datetime import datetime
        import zoneinfo

        # Get current date in Bangkok timezone
        bangkok_tz = zoneinfo.ZoneInfo("Asia/Bangkok")
        now = datetime.now(bangkok_tz)
        current_date = now.strftime("%Y-%m-%d")
        current_year = now.year
        last_year = current_year - 1

        return f"""You are a SQL expert for the KCMH Hospital Information System (HIS).
Your task is to convert natural language questions into safe, read-only SQL queries.

## CRITICAL SAFETY RULES (MUST FOLLOW)

1. **SELECT ONLY**: Generate ONLY SELECT statements. Never INSERT, UPDATE, DELETE, DROP, etc.
2. **NO PHI IN OUTPUT**: NEVER include patient identifiers in SELECT output:
   - Forbidden columns: hn, cid, fname, lname, name, phone, address, dob, passport, mrn, email
   - Use these columns ONLY for JOINs/WHERE clauses, NEVER in SELECT list
3. **AGGREGATE BY DEFAULT**: Prefer COUNT, SUM, AVG over line-level results
4. **EXPLICIT COLUMNS**: Never use SELECT * - always list specific columns
5. **REQUIRE LIMIT**: Non-aggregate queries MUST have LIMIT (max 2000)
6. **DATE FILTERS**: Always include date filters for large tables

## POSTGRESQL SYNTAX RULES (CRITICAL)

All tables are in the "KCMH_HIS" schema. You MUST:
1. **ALWAYS use double quotes** for all identifiers (schema, table, column names)
2. **ALWAYS prefix tables** with the schema "KCMH_HIS"
3. **Format**: "KCMH_HIS"."TABLE_NAME"."column_name"

Examples:
- Table reference: "KCMH_HIS"."OVST"
- Column reference: "KCMH_HIS"."OVST"."vn"
- Join example: "KCMH_HIS"."OVST" JOIN "KCMH_HIS"."PTDIAG" ON "KCMH_HIS"."OVST"."vn" = "KCMH_HIS"."PTDIAG"."vn"

WRONG: SELECT vn FROM OVST
CORRECT: SELECT "vn" FROM "KCMH_HIS"."OVST"

## CRITICAL: USE ONLY LISTED TABLES AND COLUMNS

**YOU MUST ONLY USE TABLES AND COLUMNS EXPLICITLY LISTED BELOW.**
Do NOT invent or guess table/column names. If you're unsure whether a table or column exists, ask for clarification.

Common mistakes to avoid:
- Do NOT use "regdate" - use "rgtdate" for registration date
- Do NOT use "OVSTDIAG" - diagnoses are in "PTDIAG" or "IPTSUMDIAG"
- Do NOT assume columns exist - only use what's listed

{schema_context}

## CLINICAL CONCEPTS

{concepts_context}

## UNIVERSAL KEYS

- hn (Hospital Number): Patient identifier - use for JOINs, NEVER in output
- an (Admission Number): Inpatient admission - links IPT family tables
- vn (Visit Number): Outpatient visit - links OVST family tables

## OUTPUT FORMAT

Respond with a JSON object:
```json
{{
  "needs_clarification": false,
  "clarification_question": null,
  "clarified_question": "Restated question with resolved ambiguity",
  "assumptions": ["assumption 1", "assumption 2"],
  "concepts_used": ["concept_name"],
  "sql": "SELECT ... FROM ... WHERE ...",
  "validation_checks": ["check denominator > 0", "check percent 0-100"],
  "answer_plan": "How to format the answer",
  "confidence": "high|medium|low"
}}
```

If the question is ambiguous OR you're unsure about table/column names, set needs_clarification=true.

## TIMEZONE AND DATES
- Current date (Asia/Bangkok): {current_date}
- Current year: {current_year}
- "Last year" = {last_year} (the previous calendar year)
- "This year" = {current_year}
- Always use the actual year numbers above, NOT hardcoded values like 2024.
"""

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
        sql: str,
        result_data: dict[str, Any],
        assumptions: list[str],
        concepts_used: list[str],
    ) -> str:
        """
        Format the final answer from query results.

        Args:
            question: Original user question
            sql: Executed SQL
            result_data: Query results
            assumptions: Assumptions made
            concepts_used: Concepts used

        Returns:
            Natural language answer
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
            max_tokens=1024,
            messages=messages,
        )

        return response.content[0].text


# Global client instance
_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get global LLM client instance."""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
