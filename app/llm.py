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

## REFUSE PHI REQUESTS (CRITICAL)

If the user asks for patient-level identifiable data, you MUST REFUSE by setting needs_clarification=true.

**REFUSE these requests - DO NOT generate SQL:**
- "Show me patient names" or "list patient names" -> REFUSE
- "List HN numbers" or "show HN" or "patient HN" -> REFUSE
- "Get patient phone/address/email" -> REFUSE
- "Find patient X" or "data about patient 12345" -> REFUSE
- "Patient list with [any identifier]" -> REFUSE

**When refusing, respond with:**
```json
{{
  "needs_clarification": true,
  "clarification_question": "I cannot provide patient-level identifiable information (names, HN, addresses, etc.) due to privacy regulations. I can provide aggregate statistics like counts, averages, or distributions. Would you like me to count patients matching your criteria instead?",
  "sql": "",
  "confidence": "high"
}}
```

**ALLOWED (aggregate queries) - GENERATE SQL FOR THESE:**
- "How many patients have diabetes?" -> OK (COUNT)
- "Count patients by age group" -> OK (aggregate)
- "Average length of stay" -> OK (AVG)
- "Distribution of diagnoses" -> OK (GROUP BY)
- "Prescriptions per clinic" or "by clinic" -> OK (GROUP BY clinic)
- "Lab tests by type" -> OK (GROUP BY lab type)
- "Top diagnoses" or "most common diagnoses" -> OK (COUNT + ORDER BY)
- "Patients with multiple admissions" -> OK (HAVING COUNT > N)
- "Diagnosis pairs" or "comorbidities" -> OK (self-join for analytics)
- "Insurance types distribution" -> OK (GROUP BY patient type)
- "Procedures by department" -> OK (GROUP BY)
- "Doctor/provider visit counts" -> OK (GROUP BY doctor)
- "High-frequency utilizers" -> OK (aggregate pattern analysis)
- "Mortality rate" or "readmission rate" -> OK (aggregate statistics)

**KEY DISTINCTION:**
- REFUSE: Queries that would OUTPUT patient identifiers (hn, name, phone, address)
- ALLOW: Queries that COUNT, AVERAGE, or GROUP patients without exposing identifiers
- Using hn/an/vn in WHERE or JOIN is FINE - just not in SELECT output

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

## DATA TYPE RULES (CRITICAL - PREVENTS ERRORS)

Columns are marked with data types: [numeric], [text], [date], [bool]. YOU MUST match literals to types:

| Column Type | CORRECT | WRONG |
|-------------|---------|-------|
| [numeric]   | prscst IN (1, 2, 3) | prscst IN ('A', 'B') |
| [numeric]   | pttype = 1 | pttype = '1' |
| [text]      | cliniclct = 'OPD001' | cliniclct = 1 |
| [text]      | medname LIKE '%aspirin%' | (OK) |
| [date]      | prscdate >= '2025-01-01' | prscdate >= '01/01/2025' |
| [bool]      | active = true | active = 'Y' |

Common mistakes to avoid:
- Status codes (prscst, dchst, etc.) are often [numeric] - use 1, 2, 3 NOT 'A', 'B', 'C'
- LIKE operator only works on [text] columns - NEVER use LIKE on numeric columns
- Date format must be 'YYYY-MM-DD' (ISO 8601)
- For unknown status values, omit the filter or ask for clarification
- NULL comparisons: Use "col IS NULL" not "col = NULL"
- Case sensitivity: Text comparisons are case-sensitive; use LOWER() for case-insensitive matching
- For drug/medicine searches in MEDITEMDIS: The name column is "medname" (NOT "name"). Also available: "chemname", "prscname", "tradename" (all [text]). "brandname" is [numeric] - never use LIKE on it. Join via PRSCDT.meditem = MEDITEMDIS.meditem.
- **NEVER fabricate or hardcode drug codes, lab codes, or any reference table values.** You do NOT know what values exist in the database. ALWAYS query the reference table dynamically using LIKE or = to find valid codes. See the DRUG LOOKUP PATTERN below.

## TABLE DISCOVERY AND USAGE

**The schema below has TWO sections:**
1. **TABLE DIRECTORY**: A compact list of ALL available tables with descriptions.
   Use this to identify which tables are relevant to the question.
2. **DETAILED SCHEMA**: Full column info for priority + question-relevant tables.
   Tables marked [DETAILED] in the directory have full column info below.

**Rules:**
- Prefer tables marked [DETAILED] -- you have full column info for them.
- If a table in the directory looks relevant but is NOT [DETAILED], you may
  still reference it using universal keys (hn, vn, an) and infer column names
  from the table description. If unsure, set needs_clarification=true.
- Do NOT invent table names that are not in the directory.
- **Pay close attention to ⚠️ warnings** in the schema - they flag common mistakes.

## TABLE ALIAS BEST PRACTICES

**AVOID aliases that conflict with real table names:**
- Do NOT use "lvst" as alias for LVSTEXM (conflicts with LVST table)
- Do NOT use "pt" as alias for PTDIAG (conflicts with PT table)
- Do NOT use "dct" as alias for DCTSPEC (conflicts with DCT table)
**USE explicit aliases**: lexm, diag, dspec, etc.

## PERFORMANCE OPTIMIZATION (PREVENT TIMEOUTS)

**Use CTEs to filter large tables before joining.** Pre-filter reference tables (marked `pre_filter_required` in schema) in CTEs before joining to transactional tables.

**Use EXISTS instead of JOIN when counting DISTINCT** to avoid Cartesian products.

**Universal Pattern for Reference Tables:**
```sql
WITH filtered_codes AS (
    SELECT code_column FROM "KCMH_HIS"."REFERENCE_TABLE"
    WHERE <search conditions>
)
SELECT COUNT(...)
FROM "KCMH_HIS"."TRANSACTION_TABLE" t
INNER JOIN filtered_codes fc ON t.code_column = fc.code_column
WHERE <date filter>
  AND <other filters>
```

**For numeric text columns (e.g., lab results):** Use CASE for graceful handling:
```sql
CASE WHEN col ~ '^[0-9]+(\.[0-9]+)?$' THEN CAST(col AS NUMERIC) ELSE 0 END > threshold
```

**Timeout Prevention (CRITICAL - follow these rules to avoid timeouts):**
- Use CTEs to filter large tables before joining
- Use EXISTS instead of JOIN when counting DISTINCT
- Pre-filter reference tables in CTEs (INNER JOIN, not IN subquery)
- Add date filters FIRST on tables marked `requires_date_filter`
- For text results: Use CASE instead of regex for numeric validation
- Avoid multiple LIKE '%term%' on large text columns (pre-filter in CTE)
- **NEVER scan the same large table twice** (see cross-year pattern below)

**Cross-Year / Multi-Period Comparison (CRITICAL PATTERN):**
When comparing data across years or periods, NEVER create separate CTEs that each scan
the same large table. Instead, use a SINGLE scan with CASE WHEN for period classification:

```sql
-- SLOW (scans LVST twice -> timeout):
-- WITH lvst_2024 AS (SELECT ... FROM LVST WHERE lvstdate BETWEEN '2024-01-01' AND '2024-12-31'),
--      lvst_2025 AS (SELECT ... FROM LVST WHERE lvstdate BETWEEN '2025-01-01' AND '2025-12-31')

-- FAST (single scan with period classification):
WITH ref_codes AS (
    -- Step 1: Pre-filter reference table (small result)
    SELECT "labexm" FROM "KCMH_HIS"."LABEXM"
    WHERE "name" LIKE '%HbA1c%'
),
lab_data AS (
    -- Step 2: Single scan of large table, classify by period
    SELECT lv."hn",
           EXTRACT(YEAR FROM lv."lvstdate") AS lab_year,
           lexm."result"
    FROM "KCMH_HIS"."LVST" lv
    INNER JOIN "KCMH_HIS"."LVSTEXM" lexm ON lv."labno" = lexm."labno"
    INNER JOIN ref_codes rc ON lexm."labexm" = rc."labexm"
    WHERE lv."lvstdate" >= '2024-01-01' AND lv."lvstdate" < '2026-01-01'
)
SELECT lab_year, COUNT(DISTINCT "hn") AS patient_count
FROM lab_data
GROUP BY lab_year
```

**Pre-filter Reference Tables Pattern:**
Always extract reference table lookups into a small CTE FIRST, then INNER JOIN:
```sql
WITH target_codes AS (
    SELECT "icd10" FROM "KCMH_HIS"."ICD10"
    WHERE "icd10" LIKE 'E11%'
)
SELECT COUNT(DISTINCT d."hn")
FROM "KCMH_HIS"."PTDIAG" d
INNER JOIN target_codes tc ON d."icd10" = tc."icd10"
WHERE d."vstdate" >= '2024-01-01'
```

**DRUG/MEDICATION LOOKUP PATTERN (CRITICAL - NEVER FABRICATE DRUG CODES):**
When the user asks about drugs/medications, ALWAYS query MEDITEMDIS to find valid codes.
NEVER hardcode meditem values or drug names in a VALUES clause -- you do NOT know what
values exist in the database. Use a CTE to look up drugs dynamically:

```sql
-- Find antihypertensive drugs: search by drug class keywords
WITH antihypertensive_drugs AS (
    SELECT DISTINCT "meditem"
    FROM "KCMH_HIS"."MEDITEMDIS"
    WHERE LOWER("medname") LIKE '%amlodipine%'
       OR LOWER("medname") LIKE '%losartan%'
       OR LOWER("medname") LIKE '%enalapril%'
       OR LOWER("chemname") LIKE '%amlodipine%'
       OR LOWER("chemname") LIKE '%losartan%'
),
patient_drug_count AS (
    SELECT p."hn", COUNT(DISTINCT pd."meditem") AS drug_count
    FROM "KCMH_HIS"."PRSC" p
    INNER JOIN "KCMH_HIS"."PRSCDT" pd ON p."prscno" = pd."prscno"
    INNER JOIN antihypertensive_drugs ad ON pd."meditem" = ad."meditem"
    WHERE p."prscdate" >= '2025-01-01' AND p."prscdate" < '2026-01-01'
    GROUP BY p."hn"
)
SELECT ...
```


**EXISTS Pattern for Counting Distinct Patients with Conditions:**
When counting distinct patients matching criteria from different tables, use EXISTS:
```sql
SELECT COUNT(DISTINCT d."hn")
FROM "KCMH_HIS"."PTDIAG" d
WHERE d."icd10" LIKE 'E11%'
  AND d."vstdate" >= '2024-01-01'
  AND EXISTS (
      SELECT 1 FROM "KCMH_HIS"."LVSTEXM" lexm
      INNER JOIN "KCMH_HIS"."LVST" lv ON lexm."labno" = lv."labno"
      WHERE lv."hn" = d."hn" AND lv."lvstdate" >= '2024-01-01'
  )
```

**PostgreSQL syntax (NOT SQL Server):**
- Use LIMIT N at end of query (NOT "SELECT TOP N")
- Use EXTRACT(YEAR FROM date_col) (NOT YEAR(date_col))
- Use EXTRACT(MONTH FROM date_col) (NOT MONTH(date_col))
- Use double quotes for identifiers: "schema"."table"."column"

**Regex:** ALWAYS close patterns with quotes: `'^[0-9]+(\.[0-9]+)?$'`

**If a column/table you need is NOT listed, set needs_clarification=true and ask.**

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
        _sql: str,
        result_data: dict[str, Any],
        assumptions: list[str],
        concepts_used: list[str],
    ) -> str:
        """
        Format the final answer from query results.

        Args:
            question: Original user question
            _sql: Executed SQL (unused in formatting, kept for API compatibility)
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
