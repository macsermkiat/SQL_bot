# KCMH SQL Bot -- Data Flow & External Communication

> **For IT Security Board Review** | Version 0.3.0 | VM: ddcenter-1 (`10.56.19.56`) | 2026-03-30

---

## 1. System Architecture

```
 +---------------------------------------------------------------------------+
 |  DD Server  (Internal Network  10.56.19.x)                               |
 |                                                                           |
 |   +------------------+     +------------------+     +------------------+  |
 |   | Hospital Staff   |     | KCMH SQL Bot     |     | KCMH HIS DB     |  |
 |   | (Browser)        |     | FastAPI + Uvicorn |     | PostgreSQL      |  |
 |   |                  |     | Python 3.11+      |     | (read-only user)|  |
 |   | @chula.ac.th     | --> | 10.56.19.56       | --> | 10.56.19.60/.61 |  |
 |   | @chulahospital   |     | Port :8000        |     | Port :5432      |  |
 |   |   .org           | <-- |                   | <-- | Schema: KCMH_HIS|  |
 |   +------------------+     +--------+-+--------+     | 122 tables      |  |
 |                                     | |               +------------------+  |
 +---------------------------------------------------------------------------+
                                       | |
              Outbound HTTPS :443      | |
          +----------------------------+ +----------------------------+
          |                            |                              |
          v                            v                              v
 +------------------+      +------------------+           +------------------+
 | Anthropic Claude |      | Supabase         |           | Notion API       |
 | API              |      |                  |           |                  |
 | api.anthropic.com|      | *.supabase.co    |           | api.notion.com   |
 | HTTPS :443       |      | HTTPS :443       |           | HTTPS :443       |
 |                  |      |                  |           |                  |
 | LLM: claude-     |      | Query log storage|           | Query log review |
 |  sonnet-4-6      |      | (optional)       |           | (optional)       |
 +------------------+      +------------------+           +------------------+
   REQUIRED                  OPTIONAL                       OPTIONAL
```

---

## 2. Data Flow Detail (All External Communications)

### Flow 1: SQL Bot --> Anthropic Claude API (SQL Generation)

| Field | Value |
|-------|-------|
| **Endpoint** | `api.anthropic.com` |
| **Direction** | Outbound |
| **Protocol / Port** | HTTPS :443 (TLS 1.2+) |
| **Data Sent OUT** | User question (Thai/English text), Schema metadata (table/column names, types), Concept definitions (clinical terms), Last 6 conversation messages, Error context on retries. **NO patient data. NO query results.** |
| **Data Received IN** | Generated SQL (JSON), Assumptions & confidence, Token usage counts |
| **PHI Risk** | **NONE** -- No patient data sent |

### Flow 2: SQL Bot --> Anthropic Claude API (Answer Formatting)

| Field | Value |
|-------|-------|
| **Endpoint** | `api.anthropic.com` |
| **Direction** | Outbound |
| **Protocol / Port** | HTTPS :443 (TLS 1.2+) |
| **Data Sent OUT** | User question, Query result columns & **first 20 rows** (aggregated only), Row count, truncation flag, Assumptions & concepts used |
| **Data Received IN** | Formatted Thai/English answer |
| **PHI Risk** | **LOW** -- Aggregated results only (counts, rates, sums). PHI columns blocked by SQL Guard before query execution. |

### Flow 3: SQL Bot --> PostgreSQL HIS (Internal)

| Field | Value |
|-------|-------|
| **Endpoint** | `10.56.19.60/61:5432` |
| **Direction** | Internal (never leaves org network) |
| **Protocol / Port** | TCP :5432 |
| **Data Sent** | Generated SQL (SELECT only), EXPLAIN for validation |
| **Data Received** | Query results (aggregated), Execution plan |
| **PHI Risk** | **CONTROLLED** -- Read-only user. PHI columns stripped by SQL Guard. Row limits enforced (max 2,000). |

### Flow 4: SQL Bot --> Supabase (Optional Logging)

| Field | Value |
|-------|-------|
| **Endpoint** | `*.supabase.co` |
| **Direction** | Outbound |
| **Protocol / Port** | HTTPS :443 (TLS 1.2+) |
| **Data Sent OUT** | Session ID, query group ID, User email & role, Question text, Generated SQL, Answer text, Token counts, execution time, Guard/explain validation results. **NO raw query result data.** |
| **Data Received IN** | HTTP status only (201/error) |
| **PHI Risk** | **LOW** -- Contains user email (staff, not patient). No patient data. Fire-and-forget. |

### Flow 5: SQL Bot --> Notion API (Optional Logging)

| Field | Value |
|-------|-------|
| **Endpoint** | `api.notion.com` |
| **Direction** | Outbound |
| **Protocol / Port** | HTTPS :443 (TLS 1.2+) |
| **Data Sent OUT** | Same fields as Supabase (Flow 4). **Only on successful queries.** **NO raw query result data.** |
| **Data Received IN** | HTTP status only (201/error) |
| **PHI Risk** | **LOW** -- Contains user email (staff, not patient). No patient data. Fire-and-forget. |

### Flow 6: Browser --> SQL Bot (Inbound)

| Field | Value |
|-------|-------|
| **Endpoint** | `10.56.19.56:8000` |
| **Direction** | Inbound (internal LAN only) |
| **Protocol / Port** | HTTP :8000 (behind reverse proxy for HTTPS) |
| **Data Sent IN** | Login credentials (hospital code), Question text, Session cookie |
| **Data Received OUT** | HTML pages, SSE stream (answer, SQL for super_users only), Session cookie (signed, 8hr TTL) |
| **PHI Risk** | **NONE** -- No PHI in responses. Aggregated results only. |

---

## 3. Claude API Call Frequency (Per User Question)

| Call # | Purpose | When | Data Sent to LLM | Tokens (approx) |
|--------|---------|------|-------------------|------------------|
| **1** | SQL Generation | Every question | System prompt (~4K tokens) + schema context (~8K) + concepts (~3K) + question + last 6 messages | ~15-20K input, ~1-4K output |
| **2** | Answer Formatting | After successful SQL execution | Question + first 20 result rows (aggregated) + assumptions + concepts | ~1-3K input, ~0.5-1K output |
| **3-7** | Auto-Fix Retries (if needed) | Only on SQL errors (up to 5 retries) | Same as #1 + accumulated error messages + verified column list. Extended thinking enabled. | ~20-25K input per retry |

### Summary

| Metric | Value |
|--------|-------|
| **Best case (no errors)** | 2 API calls per question (generate + format) |
| **Worst case (all retries)** | 7 API calls per question (1 initial + 5 retries + 1 format) |
| **Model** | `claude-sonnet-4-6` (configurable via `CLAUDE_MODEL` env var) |
| **Max tokens per call** | 4,096 (normal) / 16,000 (extended thinking) |

---

## 4. Personal Health Information (PHI) Protection

### Multi-Layer PHI Prevention

| Layer | Mechanism | Description |
|-------|-----------|-------------|
| **1** | LLM System Prompt | Explicit instruction to NEVER output PHI columns (`hn`, `cid`, `fname`, `lname`, `name`, `phone`, `address`, `dob`, `passport`, `mrn`, `email`). PHI allowed in JOIN/WHERE only. |
| **2** | SQL Guard (sqlglot parser) | Static analysis of generated SQL. Blocks queries that SELECT PHI columns. Enforces SELECT-only (no INSERT/UPDATE/DELETE/DROP). Validates all referenced tables/columns exist. |
| **3** | Database User | Read-only PostgreSQL user (`readonly`). Cannot modify data even if SQL guard is bypassed. |
| **4** | Row Limits | Aggregate queries by default. Non-aggregate capped at 2,000 rows. Statement timeout: 180 seconds (configurable). |
| **5** | Answer Formatting | Only aggregated results (counts, rates, grouped summaries) sent to Claude for formatting. First 20 rows max of already-filtered data. |
| **6** | Role-Based Output | Standard users see natural language answers only. Super users additionally see SQL, timing, and row counts. No user sees raw patient-level data. |

---

## 5. What Data Leaves the Organization?

| Destination | Data Sent | Contains Patient Data? | Contains PHI? | Required? |
|-------------|-----------|----------------------|---------------|-----------|
| **Anthropic** (`api.anthropic.com`) | User questions, schema metadata, clinical concept definitions, conversation history (6 msgs), aggregated query results (20 rows max) | **Aggregated only** -- Counts, rates, sums. Never individual patient records. | **NO** -- PHI columns blocked before SQL execution | **YES** -- Core functionality |
| **Supabase** (`*.supabase.co`) | Query logs: question, SQL, answer, user email, token usage, timing | **NO** | **NO** -- User email only (staff, not patient) | Optional -- Logging only. App works without it. |
| **Notion** (`api.notion.com`) | Same as Supabase (successful queries only) | **NO** | **NO** -- User email only (staff, not patient) | Optional -- Logging only. App works without it. |

---

## 6. Port & Protocol Summary

| Connection | Source | Destination | Port | Protocol | Direction | Firewall Rule |
|------------|--------|-------------|------|----------|-----------|---------------|
| User access | Hospital LAN | 10.56.19.56 | :8000 (or :443 via proxy) | HTTP/HTTPS | Inbound (internal) | Allow internal only |
| Database | 10.56.19.56 | 10.56.19.60/61 | :5432 | PostgreSQL (TCP) | Internal | Allow internal only |
| Claude API | 10.56.19.56 | api.anthropic.com | :443 | HTTPS (TLS 1.2+) | Outbound to Internet | Allow outbound :443 to api.anthropic.com |
| Supabase (optional) | 10.56.19.56 | *.supabase.co | :443 | HTTPS (TLS 1.2+) | Outbound to Internet | Allow outbound :443 (or block if not needed) |
| Notion (optional) | 10.56.19.56 | api.notion.com | :443 | HTTPS (TLS 1.2+) | Outbound to Internet | Allow outbound :443 (or block if not needed) |

---

## 7. Risk Assessment Summary

| Risk | Level | Mitigation |
|------|-------|------------|
| Patient data sent to external LLM | **LOW** | 6-layer PHI prevention. Only aggregated results (counts/rates) reach LLM for answer formatting. No individual patient records leave the server. |
| Unauthorized data modification | **NONE** | Read-only database user. SQL Guard blocks all non-SELECT statements. sqlglot AST parsing enforces this. |
| Staff credentials in external logs | **LOW** | Staff email logged to Supabase/Notion for audit trail. No passwords sent. Can disable external logging via env vars. |
| Schema metadata exposure | **LOW** | Table/column names sent to Claude for SQL generation. Contains no patient data. Required for core functionality. |
| Session hijacking | **LOW** | Signed cookies (itsdangerous). 8-hour TTL. Security headers (X-Frame-Options, CSP, etc.). |

---

## Key Takeaways for IT Board

| Item | Detail |
|------|--------|
| **External endpoints** | 3 total: Anthropic (required), Supabase (optional), Notion (optional). All HTTPS :443. |
| **Patient data leaving org** | **NONE** -- 6-layer protection ensures only aggregated statistics reach external services. |
| **LLM calls per question** | 2-7: Minimum 2 (generate + format). Up to 7 with auto-fix retries on errors. |
| **Firewall requirement** | Outbound :443 to `api.anthropic.com` (required). Supabase/Notion can be blocked if not needed. |
