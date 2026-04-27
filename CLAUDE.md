# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workflow Orchestration

### 1. Plan Node Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately - don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One tack per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: capture the pattern in memory or conversation
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes - don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests - then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

## Task Management

- Use plan mode or TodoWrite tool for multi-step tasks
- Check in with user before starting implementation
- Track progress and mark items complete as you go
- High-level summary at each step

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.

## Environment Constraints (IMPORTANT for Claude)

- **No direct database access from this working environment.** The KCMH HIS
  PostgreSQL DB lives inside the hospital intranet, reachable only via SSH
  over a VPN the user holds on their own machine. Any command that tries to
  hit the DB (psycopg, psql, `uv run python -c "from app.db import ..."`
  with a real connection) **will fail** from this sandbox. Do NOT try to
  "verify" by connecting.
- **Use dry-run validation instead.** The SQL testing pipeline
  (`tests/sql_testing/`) is built on sqlglot static validation + schema
  catalog lookup and does NOT require the DB. Prefer it for any SQL
  evaluation work (including the advisor A/B runner).
- **The user runs real SQL against the DB manually**, on their own machine
  behind the VPN. When reporting results, trust their logs rather than
  attempting a connection yourself.
- **API access is fine.** Anthropic API calls work from this environment
  provided `ANTHROPIC_API_KEY` is set in `.env` (the default line is
  commented out — ask or uncomment before running anything that hits the
  API).

## Project Overview

**KCMH SQL Bot** — a read-only analytics chatbot for querying the King Chulalongkorn Memorial Hospital (KCMH) HIS database.

The bot:
1) understands a user’s analytical question,
2) maps clinical concepts to data elements,
3) generates safe SQL,
4) executes the SQL (read-only),
5) validates the result with sanity checks,
6) replies in plain Thai/English with definitions, caveats, and (optionally) the SQL.

The end-to-end chat app is live: question -> concept mapping -> SQL generation -> execution -> Thai/English response.

## Commands

```bash
uv sync                                                          # Install dependencies
./run.sh                                                         # Start server (generates schema if needed)
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload # Dev server
uv run pytest                                                    # Run all tests
uv run pytest tests/test_sql_guard.py -v                         # Run specific test file
```

## Key Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI routes, auth endpoints, chat SSE streaming |
| `app/sql_gen.py` | SQL generation pipeline (question -> SQL) |
| `app/sql_guard.py` | SQL safety validation (SELECT-only, PHI blocking) |
| `app/llm.py` | Anthropic Claude API calls with system prompts |
| `app/schema_retriever.py` | Question-aware table/column discovery |
| `app/schema_catalog.py` | Schema knowledge loaded from parsed CSVs |
| `app/auth.py` | UserStore (CSV-based), session tokens |
| `app/concepts.py` | Clinical concept loader from `schema/concepts.yaml` |
| `app/config.py` | Settings via pydantic-settings + .env |
| `schema/concepts.yaml` | Domain knowledge: clinical terms -> SQL patterns |
| `schema/join_edges.csv` | Table join mappings with confidence scores |
| `schema/sql_corrections.yaml` | Self-learned SQL error fix patterns |
| `usr/ID.csv` | User credentials (gitignored) |
| `config/super_users.json` | Super user email list |

---

## Non-Negotiable Rules (Safety + Compliance)

### Read-only only
- SQL must be **SELECT-only** (CTEs allowed).
- Forbid: `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`, `ALTER`, `DROP`, `TRUNCATE`, `GRANT`, `REVOKE`, `COPY`, `VACUUM`, `ANALYZE`, `CALL`, `DO`.

### No patient-identifying output (PHI)
- The bot must **never return patient-level identifiers** or quasi-identifiers.
- **Disallowed** in SELECT output: `hn`, `cid`, names, phone, address, MRN, national ID, passport, exact DOB, etc.
- Default: **aggregate outputs** only (counts, rates, grouped summaries).
- If user asks for line-level patient list: refuse and offer an aggregate alternative.

### Guardrails for performance
- Enforce row caps:
  - For aggregate queries: allow small result sets.
  - For non-aggregate outputs: require `LIMIT` (e.g., 200–2000 max) and still no PHI.
- Avoid `SELECT *`. Require explicit columns.
- Prefer date filters and indexed keys (`vn`, `an`, etc.) for large tables.

### Transparency
- Provide the generated SQL in an expandable section by default (unless user asks to hide it).
- Always state assumptions and definitions (cohort, timeframe, denominators).

---

## Database Schema Knowledge

### Universal Keys (cross-table linkage)
Three keys link data across the system:
- `hn` (Hospital Number): patient identifier (PHI — do not output)
- `an` (Admission Number): inpatient admission identifier
- `vn` (Visit Number): outpatient visit identifier

- `frequent_table.csv`: Table name and description
- `frequent_column_enriched.csv`: Detailed tables' columns , PK, FK, relationship

Prefer joins with high confidence first:
(... high:universal) and (... high:table match)
Use fk_targets when you want “this column references what?”
Use join_peers when you want “what can I join this column to?” (great for building join graphs)
If join_warning is present, treat that edge as suspicious and prefer the “home key” interpretation.

- `join_edges.csv`: join mapping file 
= `relationships.md`: Table family 
---

## Product Spec: Chatbot Behavior

### User questions (examples)
- “How many people have diabetes in OPD last year?”
- “What percentage of lab orders were bundle thyroid function test (FT3, FT4, TSH) last year?”

### Required capabilities
1) **Intent parsing**: metric, cohort, time window, grouping, filters, denominator.
2) **Concept resolution**:
   - If mapping is ambiguous or missing: ask clarifying question OR propose a default with explicit caveat.
3) **SQL generation**:
   - Use CTEs.
   - Explicit joins.
   - Explicit date filter.
   - Never output PHI fields.
4) **SQL verification (two-pass)**:
   - Static guard: parse with `sqlglot`; enforce allowlist; check referenced tables/columns exist.
   - Semantic self-check: ensure SQL aligns with question definitions.
5) **Execution**:
   - Read-only DB user.
   - Timeout.
   - Capture runtime, rowcount.
6) **Result validation**:
   - Run at least one sanity check query when applicable:
     - denominator check
     - range check (percent 0–100)
     - alternate formulation check (patients vs visits) when cheap
   - If suspicious, revise SQL and retry once with explanation.
7) **Answer generation**:
   - Direct answer with numbers.
   - Definitions used + timeframe.
   - Caveats and confidence grade (High/Medium/Low).

### Time semantics
- Timezone: **Asia/Bangkok**
- “Last year” = previous calendar year relative to current date.

---

## Tech Stack

- Python 3.11+, **uv** package manager
- **Backend**: FastAPI + uvicorn
- **Frontend**: Jinja2 templates + static JS/CSS (space theme), served from `app/templates/` and `app/static/`
- **LLM**: Anthropic Claude API (`anthropic` SDK)
- **SQL parsing/guard**: sqlglot
- **DB driver**: psycopg + psycopg-pool
- **Config**: pydantic-settings + python-dotenv (`.env` file)
- **Auth**: itsdangerous signed cookies

---

## Authentication

- **CSV-based credentials**: `usr/ID.csv` (columns: NAME, ID, Department, E-mail)
- **Self-registration**: `/register` — requires @chula.ac.th or @chulahospital.org email, 7-digit hospital code as password
- **Super users**: Listed in `config/super_users.json`
- **Sessions**: Signed cookies via itsdangerous (URLSafeTimedSerializer)
- **Passwords**: Hospital code (ID column) used as plaintext password — no hashing

### User Roles
1. **super_user**: Sees generated SQL, query execution time, row count
2. **standard_user**: Sees only natural language answers with aggregated results, no SQL



## Thai Language Context

The database uses Thai for comments and some values. Common terms:

วันที่ (date), รหัส (code/ID), ชื่อ (name), หมายเหตุ (note), สถานะ (status)

When responding:

Prefer the user’s language (Thai if the question is Thai, otherwise English).

Keep medical/clinical definitions explicit and conservative.

---

## How Claude Should Work in This Repo

When implementing features:

**Schema & SQL**:
- Ground all schema usage in relationship table (do not guess).
- Build the SQL guard early (before fancy UI).
- Add concept mappings incrementally in concepts.yaml.


**Testing**:
Write tests for:
- safe SQL enforcement
- PHI output blocking
- Authentication (login, logout, session validation)
- Role-based response filtering

**Logging & Transparency**:
- Keep outputs deterministic and log decisions (assumptions, mappings, confidence).
- Log all queries with username, timestamp, and execution time
- For super users: include SQL in logs

**Safe Fallbacks**:
If an answer cannot be produced safely or unambiguously:
- Ask a clarifying question, or
- Provide a safe partial answer (e.g., show which tables appear relevant) without executing risky queries.


---
