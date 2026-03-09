"""
Claude API wrapper for SQL generation.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from app.config import get_settings
from app.models import SQLGenerationResponse, TokenUsage


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
        extended_thinking: bool = False,
    ) -> tuple[SQLGenerationResponse, TokenUsage]:
        """
        Generate SQL from natural language question.

        Args:
            user_question: User's analytical question
            schema_context: Schema information (tables, columns)
            concepts_context: Clinical concept definitions
            conversation_history: Previous messages for context
            extended_thinking: Enable extended thinking for harder reasoning

        Returns:
            Tuple of (SQLGenerationResponse, TokenUsage)
        """
        system_prompt = self._build_system_prompt(schema_context, concepts_context)
        messages = self._build_messages(user_question, conversation_history)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 16000 if extended_thinking else 4096,
            "system": system_prompt,
            "messages": messages,
        }

        if extended_thinking:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": 10000,
            }

        try:
            response = self._client.messages.create(**kwargs)
        except Exception:
            if extended_thinking:
                # Fall back without extended thinking
                kwargs.pop("thinking", None)
                kwargs["max_tokens"] = 4096
                response = self._client.messages.create(**kwargs)
            else:
                raise

        usage = TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
        )

        # Extract text content (skip thinking blocks when extended thinking is used)
        text_content = ""
        for block in response.content:
            if block.type == "text":
                text_content = block.text
                break

        return self._parse_response(text_content), usage

    def _build_system_prompt(self, schema_context: str, concepts_context: str) -> str:
        """Build the system prompt with schema and concept context.

        Compact format to minimize token usage (~5K static + schema + concepts).
        """
        from datetime import datetime
        import zoneinfo

        bangkok_tz = zoneinfo.ZoneInfo("Asia/Bangkok")
        now = datetime.now(bangkok_tz)
        current_date = now.strftime("%Y-%m-%d")
        current_year = now.year
        last_year = current_year - 1

        return f"""You are a SQL expert for KCMH HIS. Convert questions to safe, read-only PostgreSQL.

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
- Drug search: MEDITEMDIS."tradename" LIKE '%%keyword%%'. "brandname" is numeric, never LIKE. Join: PRSCDT.meditem=MEDITEMDIS.meditem.
- PRSC-PRSCDT join: ALWAYS use prscno AND sphmlct. NEVER use prvno. Example: PRSC p JOIN PRSCDT pd ON p."prscno"=pd."prscno" AND p."sphmlct"=pd."sphmlct"
- Drug class counting: When question asks >=N drug types/classes, count pharmacological CLASSES (ACEi, ARB, CCB, diuretic, beta-blocker), NOT individual drug items. Use CASE on chemname/tradename to classify, then COUNT(DISTINCT class). Must be concurrent (same prescription), not cumulative over time.
- NEVER fabricate or hardcode meditem/ICD codes in VALUES clauses. Always query reference tables dynamically (e.g., SELECT meditem FROM MEDITEMDIS WHERE LOWER(tradename) LIKE '%keyword%'). Use LIKE 'J44%' for ICD ranges, not enumerated VALUES lists.
- Temporal drug-condition: "already on drug" = prscdate BEFORE event. "despite treatment" = measurement AFTER prscdate. Always enforce date ordering when question implies temporal relationship.
- ICD-9-CM codes (icd9cm columns) are stored WITHOUT dots. '47.01' is stored as '4701', '47.09' as '4709'. Use LIKE '470%' NOT '47.0%'. Applies to: IPTSUMOPRT, PTICD9CM, PTOPRT, ICD9CM, OPRTACT.
- Use IS NULL not =NULL. LOWER() for case-insensitive text. Status codes are often numeric.

## TABLE SCHEMA
Two sections: TABLE DIRECTORY (all tables, compact) + DETAILED SCHEMA (columns for selected tables).
- Prefer [DETAILED] tables. Non-detailed can use universal keys (hn/vn/an).
- Do NOT invent tables. Heed ! warnings for common column mistakes.
- Aliases: never use "lvst" for LVSTEXM, "pt" for PTDIAG, "dct" for DCTSPEC.

## TABLE ROUTING (use the RIGHT table)
- Emergency/ER visits -> CNER (NOT OVST.emrgncy which is just urgency triage level)
- Emergency vs elective surgery -> OPREQVST.optype (1=Elective, 2=Emergency). IPT.receiveflag is NOT populated.
- Surgery/procedure dates -> IPTSUMOPRT.indate or PTOPRT.oprtdatein (actual procedure times)
- ICD-9-CM procedure codes -> PTICD9CM.icd9cm or IPTSUMOPRT.icd9cm (PTOPRT.icd9cm is mostly empty)
- OR scheduling/surgery details -> OPREQVST (has an, optype, estmdate)
- Delivery/birth -> DLVST, DLVSTDESC, DLVSTEXT
- Blood pressure/vitals -> OVSTPRESS
- ICU bookings -> IPTBOOKBEDICU
- Radiology/imaging -> RDOEXM
- Lab results -> LVSTEXM directly (has hn, lvstdate, labexm, result). Do NOT join LVST unless you need LVST-only columns. LVSTEXM is self-sufficient for most lab queries.
- Detail tables may lack hn/vn/an. Check "Header-Detail Join Rules" in schema context for required JOINs.

## PERFORMANCE
- Pre-filter ref tables in CTEs, INNER JOIN to transaction tables.
- EXISTS not JOIN for COUNT(DISTINCT) across tables.
- Cross-year: single scan + EXTRACT(YEAR FROM date), never scan same table twice.
- Numeric text (lab results): CASE WHEN col ~ '^[0-9]+(\\.[0-9]+)?$' THEN CAST(col AS NUMERIC) END

## KEY PATTERNS
ICD lookup (OPD - PTDIAG has hn):
```sql
WITH codes AS (SELECT "icd10" FROM "KCMH_HIS"."ICD10" WHERE "icd10" LIKE 'E11%')
SELECT COUNT(DISTINCT d."hn") FROM "KCMH_HIS"."PTDIAG" d
INNER JOIN codes c ON d."icd10"=c."icd10" WHERE d."vstdate">='{last_year}-01-01'
```
ICD lookup (IPD - IPTSUMDIAG has NO hn, must JOIN IPT):
```sql
SELECT COUNT(DISTINCT ipt."hn") FROM "KCMH_HIS"."IPTSUMDIAG" d
INNER JOIN "KCMH_HIS"."IPT" ipt ON d."an"=ipt."an"
WHERE d."icd10" LIKE 'E11%' AND ipt."dchdate">='{last_year}-01-01'
```
Drug lookup (never hardcode codes):
```sql
WITH drugs AS (SELECT DISTINCT "meditem" FROM "KCMH_HIS"."MEDITEMDIS" WHERE LOWER("tradename") LIKE '%drug_name%')
SELECT COUNT(DISTINCT p."hn") FROM "KCMH_HIS"."PRSC" p
INNER JOIN "KCMH_HIS"."PRSCDT" pd ON p."prscno"=pd."prscno" AND p."sphmlct"=pd."sphmlct"
INNER JOIN drugs d ON pd."meditem"=d."meditem" WHERE p."prscdate">='{last_year}-01-01'
```
PRSC-PRSCDT join: ALWAYS use both prscno AND sphmlct (pharmacy unit). Never use prvno for joining.

{schema_context}

## CONCEPTS
{concepts_context}

## KEYS
- hn: patient ID (PHI, JOIN only) | an: inpatient admission | vn: outpatient visit

## OUTPUT (JSON only)
```json
{{{{"needs_clarification":false,"clarification_question":null,"clarified_question":"...","assumptions":["..."],"concepts_used":["..."],"sql":"SELECT ...","validation_checks":["..."],"answer_plan":"...","confidence":"high|medium|low"}}}}
```
If unsure about table/column, set needs_clarification=true.

## DATES
Today: {current_date} | Year: {current_year} | Last year: {last_year}
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
            max_tokens=1024,
            messages=messages,
        )

        usage = TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
        )

        return response.content[0].text, usage


# Global client instance
_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get global LLM client instance."""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
