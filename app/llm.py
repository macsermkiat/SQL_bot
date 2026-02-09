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
- For drug/medicine searches: Always search multiple name fields (medname, tradename, chemname, brandname)

## CRITICAL: USE ONLY LISTED TABLES AND COLUMNS

**YOU MUST ONLY USE TABLES AND COLUMNS EXPLICITLY LISTED BELOW.**
Do NOT invent or guess table/column names. If you're unsure whether a table or column exists, ask for clarification.

## CRITICAL SCHEMA CORRECTIONS (VALIDATED WITH 40 CLINICAL QUERIES)

### Prescription Tables - PRSCDT.meditem (NOT meditemdis) + Missing `hn`
**Column name correction:**
**WRONG**: PRSCDT.meditemdis = MEDITEMDIS.meditemdis
**CORRECT**: PRSCDT.meditem = MEDITEMDIS.meditem

- PRSCDT has FK column named **meditem** (NOT meditemdis)
- MEDITEMDIS has PK column named **meditem** (NOT meditemdis)

**PRSCDT does NOT have `hn` column:**
- PRSCDT only has `prscno` and `meditem` (no patient identifier)
- MUST JOIN to PRSC table to get `hn`, `vn`, or `prscdate`
- Join pattern: "KCMH_HIS"."PRSC" p JOIN "KCMH_HIS"."PRSCDT" pd ON p.prscno = pd.prscno

### Procedure Tables - IPTSUMOPRT.indate (NOT oprdate)
**WRONG**: WHERE EXTRACT(YEAR FROM IPTSUMOPRT.oprdate) = 2025
**CORRECT**: WHERE EXTRACT(YEAR FROM IPTSUMOPRT.indate) = 2025

- IPTSUMOPRT has **indate** for procedure start date (NOT oprdate)
- IPTSUMOPRT has **outdate** for procedure end date
- IPTSUMOPRT has **icd9cm** for procedure code

### Lab Tables - LVST vs LVSTEXM (TWO DIFFERENT TABLES!)
**LVST** (Lab order header):
- Columns: hn, lvstdate, labgrp, an, dct, ln, labno
- Does NOT have: labexm, result
- Purpose: Lab order metadata

**LVSTEXM** (Lab exam results):
- Columns: hn, lvstdate, labexm, result, an, ln, labno
- Has: labexm (FK to LABEXM), result
- Purpose: Individual lab test results

**CRITICAL**: Do NOT use alias "lvst" for LVSTEXM table (causes validation errors)
**USE**: Explicit aliases like "lexm" or "lvstexm" instead

**CORRECT lab result query**:
```sql
FROM "KCMH_HIS"."LVSTEXM" lexm
JOIN "KCMH_HIS"."LABEXM" lab ON lexm.labexm = lab.labexm
WHERE LOWER(lab.name) LIKE '%hemoglobin%'
  AND CAST(lexm.result AS NUMERIC) > 10
```

### IPT Table - Missing Columns
**IPT has NO age column**:
- To filter by age, JOIN with PT table and calculate: EXTRACT(YEAR FROM AGE(CURRENT_DATE, PT.birthdate))
- Or omit age filter and ask for clarification

**IPT has NO admtype column**:
- Cannot distinguish emergency vs elective admissions
- Ask user for clarification or use alternate criteria

### IPTSUMDIAG Table - Missing `hn` Column (CRITICAL!)
**IPTSUMDIAG does NOT have `hn` column**:
- IPTSUMDIAG only has `an` (admission number)
- To get patient identifier `hn`, you MUST JOIN to IPT table
- **WRONG**: `SELECT hn FROM IPTSUMDIAG` (will fail!)
- **CORRECT**: `SELECT i.hn FROM IPTSUMDIAG d JOIN IPT i ON d.an = i.an`

**Example - Count diabetes patients from inpatient diagnoses:**
```sql
-- WRONG (will error: column "hn" does not exist)
SELECT COUNT(DISTINCT hn) FROM IPTSUMDIAG WHERE icd10 >= 'E10' AND icd10 < 'E15'

-- CORRECT (JOIN to IPT for hn)
SELECT COUNT(DISTINCT i.hn)
FROM "KCMH_HIS"."IPTSUMDIAG" d
JOIN "KCMH_HIS"."IPT" i ON d.an = i.an
WHERE d.icd10 >= 'E10' AND d.icd10 < 'E15'
```

### Header-Detail Table Pattern (CRITICAL!)
Many tables follow a **header-detail pattern** where detail tables DON'T have `hn` column:

**PRSCDT (Prescription Detail) - Missing `hn` Column:**
- PRSCDT only has `prscno` (prescription number) and `meditem` (medication code)
- To get patient identifier `hn`, you MUST JOIN to PRSC (prescription header)
- **WRONG**: `SELECT hn FROM PRSCDT` (will fail!)
- **CORRECT**: `SELECT p.hn FROM PRSC p JOIN PRSCDT pd ON p.prscno = pd.prscno`

**Example - Count patients prescribed Dilantin:**
```sql
-- WRONG (will error: column "hn" does not exist)
SELECT COUNT(DISTINCT hn)
FROM PRSCDT
WHERE meditem IN (SELECT meditem FROM MEDITEMDIS WHERE medname LIKE '%dilantin%')

-- CORRECT (JOIN to PRSC for hn)
SELECT COUNT(DISTINCT p.hn)
FROM "KCMH_HIS"."PRSC" p
JOIN "KCMH_HIS"."PRSCDT" pd ON p.prscno = pd.prscno
WHERE pd.meditem IN (SELECT meditem FROM MEDITEMDIS WHERE medname LIKE '%dilantin%')
```

**General Pattern - Always JOIN detail to header:**
- **PRSC** (header: has `hn`, `vn`, `prscdate`) + **PRSCDT** (detail: has `meditem`, `prscno`)
- **IPT** (header: has `hn`, `an`, `indate`) + **IPTSUMDIAG/IPTSUMOPRT** (detail: has `an`, diagnosis/procedure)
- **OVST** (header: has `hn`, `vn`, `vstdate`) + **PTDIAG/PTOPRT** (detail: has `vn`, diagnosis/procedure)

### Table Alias Best Practices
**AVOID aliases that conflict with real table names**:
- Do NOT use "lvst" as alias for LVSTEXM (conflicts with LVST table)
- Do NOT use "pt" as alias for PTDIAG (conflicts with PT table)
- Do NOT use "dct" as alias for DCTSPEC (conflicts with DCT table)
**USE explicit aliases**: lexm, diag, dspec, etc.

## PERFORMANCE OPTIMIZATION (PREVENT TIMEOUTS)

### Use CTEs to Filter Early
When joining multiple large tables, filter data FIRST using CTEs (Common Table Expressions):

**SLOW (joins everything then filters):**
```sql
SELECT COUNT(DISTINCT o.vn)
FROM OVST o
JOIN PTDIAG d ON o.vn = d.vn
JOIN PRSC p ON o.vn = p.vn
JOIN PRSCDT pd ON p.prscno = pd.prscno
WHERE EXTRACT(YEAR FROM o.vstdate) = 2025
  AND d.icd10 >= 'E10' AND d.icd10 < 'E15'
  AND pd.meditem IN (...)
```

**FAST (filters first, then joins small sets):**
```sql
WITH diabetes_visits AS (
    SELECT DISTINCT vn FROM "KCMH_HIS"."PTDIAG"
    WHERE icd10 >= 'E10' AND icd10 < 'E15'
    AND EXTRACT(YEAR FROM vstdate) = 2025
),
drug_visits AS (
    SELECT DISTINCT p.vn
    FROM "KCMH_HIS"."PRSC" p
    JOIN "KCMH_HIS"."PRSCDT" pd ON p.prscno = pd.prscno
    WHERE pd.meditem IN (...)
)
SELECT COUNT(DISTINCT o.vn)
FROM "KCMH_HIS"."OVST" o
WHERE EXTRACT(YEAR FROM o.vstdate) = 2025
  AND EXISTS (SELECT 1 FROM diabetes_visits dv WHERE dv.vn = o.vn)
  AND EXISTS (SELECT 1 FROM drug_visits dg WHERE dg.vn = o.vn)
```

### Use EXISTS Instead of JOIN for Counting
When counting DISTINCT values, use EXISTS instead of JOIN to avoid Cartesian products:

**SLOW (JOIN creates many duplicate rows):**
```sql
SELECT COUNT(DISTINCT vn)
FROM OVST o
JOIN PTDIAG d ON o.vn = d.vn
WHERE d.icd10 LIKE 'E11%'
```

**FAST (EXISTS checks without duplicates):**
```sql
SELECT COUNT(DISTINCT vn)
FROM "KCMH_HIS"."OVST" o
WHERE EXISTS (
    SELECT 1 FROM "KCMH_HIS"."PTDIAG" d
    WHERE d.vn = o.vn AND d.icd10 LIKE 'E11%'
)
```

### Pre-filter Reference Tables (CRITICAL PATTERN!)
**ALWAYS pre-filter small lookup tables BEFORE joining to large transactional tables.**

Reference tables to pre-filter:
- **MEDITEMDIS** (medications) - ~10K rows
- **ICD10** (diagnoses) - ~15K rows
- **ICD9CM** (procedures) - ~5K rows
- **LABEXM** (lab tests) - ~2K rows

#### Medication Example:
**SLOW (searches drug names on every prescription):**
```sql
FROM PRSCDT pd
JOIN MEDITEMDIS m ON pd.meditem = m.meditem
WHERE LOWER(m.medname) LIKE '%metformin%'
```

**FAST (pre-filter medications in CTE):**
```sql
WITH metformin_drugs AS (
    SELECT meditem FROM "KCMH_HIS"."MEDITEMDIS"
    WHERE LOWER(medname) LIKE '%metformin%'
       OR LOWER(tradename) LIKE '%metformin%'
       OR LOWER(chemname) LIKE '%metformin%'
)
SELECT ...
FROM "KCMH_HIS"."PRSCDT" pd
JOIN metformin_drugs m ON pd.meditem = m.meditem
```

#### Procedure Example (ICD9CM):
**Pattern: For ANY procedure query, pre-filter ICD9CM table first**
```sql
WITH target_procedures AS (
    SELECT icd9cm FROM "KCMH_HIS"."ICD9CM"
    WHERE icd9cm LIKE '01.2%'  -- Code pattern
       OR LOWER(name) LIKE '%craniotomy%'
       OR LOWER(thainame) LIKE '%craniotomy%'
)
SELECT COUNT(*)
FROM "KCMH_HIS"."IPTSUMOPRT" ip
WHERE ip.icd9cm IN (SELECT icd9cm FROM target_procedures)
  AND EXTRACT(YEAR FROM ip.indate) = 2025
```

#### Diagnosis Example (ICD10):
**Pattern: For complex diagnosis searches, pre-filter ICD10 table first**
```sql
WITH cancer_codes AS (
    SELECT icd10 FROM "KCMH_HIS"."ICD10"
    WHERE icd10 >= 'C00' AND icd10 < 'D00'  -- Cancer range
       OR LOWER(name) LIKE '%cancer%'
       OR LOWER(thainame) LIKE '%มะเร็ง%'
)
SELECT COUNT(DISTINCT hn)
FROM "KCMH_HIS"."PTDIAG"
WHERE icd10 IN (SELECT icd10 FROM cancer_codes)
```

#### Lab Test Example (LABEXM):
```sql
WITH thyroid_tests AS (
    SELECT labexm FROM "KCMH_HIS"."LABEXM"
    WHERE LOWER(name) LIKE '%tsh%'
       OR LOWER(name) LIKE '%t3%'
       OR LOWER(name) LIKE '%t4%'
)
-- Use JOIN instead of IN for better performance
SELECT COUNT(DISTINCT lexm.ln)
FROM "KCMH_HIS"."LVSTEXM" lexm
INNER JOIN thyroid_tests tt ON lexm.labexm = tt.labexm
WHERE EXTRACT(YEAR FROM lexm.lvstdate) = 2025
```

#### Numeric Result Validation (Lab Results):
**For LVSTEXM.result filtering (CRITICAL - prevents timeouts!):**

**SLOW (regex on millions of rows):**
```sql
SELECT DISTINCT hn
FROM "KCMH_HIS"."LVSTEXM"
WHERE labexm IN (SELECT labexm FROM ...)
  AND result ~ '^[0-9]+(\.[0-9]+)?$'
  AND CAST(result AS NUMERIC) > 200
```

**FAST (use CASE for graceful handling):**
```sql
SELECT DISTINCT lexm.hn
FROM "KCMH_HIS"."LVSTEXM" lexm
INNER JOIN filtered_tests ft ON lexm.labexm = ft.labexm
WHERE EXTRACT(YEAR FROM lexm.lvstdate) = 2025
  AND lexm.result IS NOT NULL
  AND CASE
        WHEN lexm.result ~ '^[0-9]+(\.[0-9]+)?$'
        THEN CAST(lexm.result AS NUMERIC)
        ELSE 0
      END > 200
```

**Key points:**
- Use **INNER JOIN** instead of `IN (subquery)` for better index usage
- Use **CASE** to handle invalid values (returns 0 for non-numeric)
- Filter by date BEFORE checking result values
- ALWAYS use proper regex syntax: `'^[0-9]+(\.[0-9]+)?$'` (don't forget closing `'$`)

### Always Add Date Filters Early
Large tables (OVST, IPT, PRSC, LVST, LVSTEXM) MUST have date filters:
```sql
WHERE EXTRACT(YEAR FROM vstdate) = 2025  -- REQUIRED for OVST
WHERE EXTRACT(YEAR FROM lvstdate) = 2025  -- REQUIRED for LVSTEXM
```

**CRITICAL: LVSTEXM is EXTREMELY LARGE** (millions of lab results)
- ALWAYS filter by date first: `EXTRACT(YEAR FROM lvstdate) = year`
- ALWAYS use INNER JOIN (not IN) when joining to reference tables
- For result filtering, use CASE instead of regex validation
- Example:
```sql
-- GOOD: Date filter + JOIN + CASE
SELECT DISTINCT lexm.hn
FROM "KCMH_HIS"."LVSTEXM" lexm
INNER JOIN filtered_tests ft ON lexm.labexm = ft.labexm
WHERE EXTRACT(YEAR FROM lexm.lvstdate) = 2025
  AND CASE WHEN lexm.result ~ '^[0-9.]+$' THEN CAST(lexm.result AS NUMERIC) ELSE 0 END > 200

-- BAD: Will timeout!
SELECT DISTINCT hn FROM "KCMH_HIS"."LVSTEXM"
WHERE result ~ '^[0-9]+$' AND CAST(result AS NUMERIC) > 200
```

### Summary: Timeout Prevention Checklist
- ✅ Use CTEs to filter large tables before joining
- ✅ Use EXISTS instead of JOIN when counting DISTINCT
- ✅ **Pre-filter reference tables (MEDITEMDIS, ICD9CM, ICD10, LABEXM) in CTEs**
- ✅ **Use INNER JOIN instead of IN (subquery) for better index usage**
- ✅ Add date filters FIRST, then other filters
- ✅ For LVSTEXM.result: Use CASE instead of regex for numeric validation
- ✅ Avoid multiple LIKE '%term%' on large text columns (pre-filter in CTE)

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

**Common column name ERRORS to avoid:**
- Do NOT use "regdate" -> use "rgtdate" for registration date
- Do NOT use "admdate" -> IPT uses "rgtdate" for admission/registration date
- Do NOT use "rgttime" -> OVST does not have rgttime; use "rgtdate" or "vsttime"
- Do NOT use "OVSTDIAG" -> diagnoses are in "PTDIAG" or "IPTSUMDIAG"
- Do NOT use "PRSC.cliniclct" -> PRSC does not have cliniclct column; use OVST.cliniclct
- Do NOT use "CLINICLCT.cliniclctnm" -> use "CLINICLCT.name"
- Do NOT use "doctorname" -> use DCT table with dct code
- Do NOT use "labexmnm" -> use "LABEXM.name" for lab test name
- Do NOT use "LVST.vstdate" -> use "LVST.lvstdate" for lab order date
- Do NOT use "LVSTEXM.labresult" -> use "LVSTEXM.result" for lab result

**Common REGEX ERRORS to avoid:**
- ALWAYS close regex patterns with quotes: `result ~ '^[0-9]+(\.[0-9]+)?$'` (NOT `result ~ '^[0-9]+(\.[0-9]+)?`)
- Use `$` to match end of string: `'^[0-9]+$'` matches numeric only
- Escape special chars in LIKE: Use `LOWER(col) LIKE '%term%'` for simple text search
- For numeric validation, consider: `result ~ '^[0-9]+(\.[0-9]+)?$'` before CAST

**PostgreSQL syntax (NOT SQL Server):**
- Use LIMIT N at end of query (NOT "SELECT TOP N")
- Use EXTRACT(YEAR FROM date_col) (NOT YEAR(date_col))
- Use EXTRACT(MONTH FROM date_col) (NOT MONTH(date_col))
- Use double quotes for identifiers: "schema"."table"."column"

**CORRECT join patterns for clinics:**
- Prescriptions by clinic: PRSC -> OVST (via vn) -> CLINICLCT (via cliniclct)
- Visits by clinic: OVST -> CLINICLCT (via cliniclct)

**CORRECT join patterns for labs:**
- Lab results: LVSTEXM -> LABEXM (via labexm) for test names/results
- Lab orders: LVST -> LVSTEXM (via labno) if you need order metadata

**CORRECT join patterns for drugs:**
- Drug prescriptions: PRSC -> PRSCDT (via prscno) -> MEDITEMDIS (via meditem)
- Search drug names in these TEXT columns ONLY:
  - MEDITEMDIS.medname (primary drug name)
  - MEDITEMDIS.tradename (trade name)
  - MEDITEMDIS.chemname (chemical name)
- DO NOT search in brandname column (it's numeric, not text!)
- Example: LOWER(m.medname) LIKE '%metformin%' OR LOWER(m.tradename) LIKE '%metformin%' OR LOWER(m.chemname) LIKE '%metformin%'

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
