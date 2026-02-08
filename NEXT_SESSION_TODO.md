# Next Session TODO

## Quick Start Commands

```bash
# Navigate to project
cd "/Users/admin/Project_Chatbot_research/SQL bot"

# Run full test suite
python -m tests.sql_testing.run_clinical_batches

# Check specific question
python -m tests.sql_testing.evaluator CQ001
```

---

## Current Status (As of Feb 8, 2025)

✅ **40 complex clinical SQL questions validated**
- Pass+Warn Rate: 100% (0 failures)
- Pass Rate: 15% (6/40)
- Warn Rate: 85% (34/40)

✅ **Schema corrections identified and applied**
- PRSCDT.meditem (NOT meditemdis)
- IPTSUMOPRT.indate (NOT oprdate)
- LVST vs LVSTEXM distinction
- Table alias conflicts resolved

---

## Choose Your Path

### Path A: Improve Pass Rate (15% → 90%+)

**Goal**: Convert warnings to passes by improving schema documentation.

**Steps**:
1. Run evaluation and capture warnings:
   ```bash
   python -m tests.sql_testing.run_clinical_batches > results.txt 2>&1
   grep "join_confidence" results.txt | sort | uniq -c | sort -rn | head -20
   ```

2. Identify top 10 most common low-confidence joins

3. Update schema files with explicit FK relationships:
   - `schema/frequent_column_enriched.csv` - Add fk_targets
   - `schema/join_edges.csv` - Promote heuristic→high confidence
   - `schema/relationships.md` - Document join patterns

4. Regenerate schema_knowledge.json:
   ```bash
   python -m app.schema_parser
   ```

5. Re-run tests and measure improvement

**Expected Outcome**: 80-90% pass rate (most joins become high-confidence)

---

### Path B: Integrate into Production App

**Goal**: Apply schema corrections to main SQL generation.

**Steps**:
1. Read current prompt in `app/llm.py`:
   ```bash
   grep -A 50 "SCHEMA_CONTEXT" app/llm.py
   ```

2. Add schema corrections from `tests/sql_testing/SCHEMA_CORRECTIONS.md`:
   - PRSCDT.meditem (NOT meditemdis)
   - MEDITEMDIS.meditem PK (NOT meditemdis)
   - IPTSUMOPRT.indate (NOT oprdate)
   - LVST vs LVSTEXM distinction
   - IPT missing age/admtype columns
   - Table alias guidance

3. Test with sample questions:
   ```python
   from app.llm import generate_sql

   questions = [
       "How many diabetic patients on metformin?",
       "Count patients on warfarin with high INR",
       "Find hip replacements in osteoarthritis patients"
   ]

   for q in questions:
       sql = generate_sql(q)
       print(f"Q: {q}\nSQL: {sql}\n")
   ```

4. Run through evaluator to verify no schema errors

**Expected Outcome**: Production SQL generation uses corrected schema knowledge

---

### Path C: Expand Test Coverage

**Goal**: Create more diverse test cases.

**Steps**:
1. Create new question batches:
   - **Temporal queries**: "Patients whose creatinine increased after furosemide"
   - **Aggregations**: "Average HbA1c by age group"
   - **Subqueries**: "Patients NOT on aspirin despite heart disease"
   - **CASE statements**: "Categorize BP as normal/elevated/hypertensive"
   - **Date arithmetic**: "Readmissions within 30 days"

2. Add to `test_data/sql_testing/questions/`:
   - `temporal_questions.json`
   - `aggregation_questions.json`
   - `subquery_questions.json`

3. Generate expected SQL (manually or with subagents)

4. Run through evaluator

**Expected Outcome**: 100+ validated questions covering edge cases

---

### Path D: Performance Testing

**Goal**: Test SQL execution on real database.

**Steps**:
1. Get read-only DB credentials (if not already available)

2. Create connection utility:
   ```python
   # app/db_executor.py
   def execute_with_timeout(sql: str, timeout_ms: int = 15000):
       # Set statement_timeout
       # Execute query
       # Capture timing, row count
       pass
   ```

3. Run validated queries on real DB:
   ```bash
   python -m tests.sql_testing.performance_test
   ```

4. Identify slow queries (>2 seconds)

5. Optimize:
   - Add indexes
   - Rewrite joins
   - Add date filters
   - Limit result sets

**Expected Outcome**: All queries execute in <2 seconds with proper indexes

---

## Recommended: Start with Path B (Production Integration)

**Why?**
1. Schema corrections already identified - easy to apply
2. Immediate impact on production SQL quality
3. Low effort, high value
4. Sets foundation for other paths

**Time Estimate**: 1-2 hours

**Steps**:
1. Update `app/llm.py` schema context (30 min)
2. Test with sample questions (30 min)
3. Run evaluator on generated SQL (15 min)
4. Fix any issues (15 min)

---

## Files to Review

### Documentation (Read These First)
- `tests/sql_testing/SESSION_PROGRESS.md` - Full session summary
- `tests/sql_testing/SCHEMA_CORRECTIONS.md` - Critical corrections to apply
- `task_plan.md` - Overall project plan and status

### Test Results
- `tests/sql_testing/clinical_batch1_results.py` - CQ001-CQ010
- `tests/sql_testing/clinical_batch2_results.py` - CQ011-CQ020
- `tests/sql_testing/clinical_batch3_results.py` - CQ021-CQ030
- `tests/sql_testing/clinical_batch4_results.py` - CQ031-CQ040

### Core Application
- `app/llm.py` - SQL generation prompt (needs updates)
- `app/sql_guard.py` - Safety validation (working)
- `app/schema_catalog.py` - Schema knowledge (working)

### Schema Files
- `schema/frequent_column_enriched.csv` - Column metadata
- `schema/join_edges.csv` - Join mappings
- `schema/relationships.md` - Table families

---

## Quick Wins for Next Session

1. **Fix most common error** (15 min):
   - Update app/llm.py: "Use PRSCDT.meditem NOT meditemdis"

2. **Add table alias warning** (10 min):
   - Update app/llm.py: "Don't use 'lvst' as alias for LVSTEXM"

3. **Document missing columns** (10 min):
   - Update app/llm.py: "IPT has no age or admtype columns"

4. **Test with real question** (15 min):
   - Generate SQL for "diabetic patients on metformin"
   - Verify it passes all 6 validation layers

Total: ~50 minutes to apply critical fixes

---

## Success Metrics

After next session, you should have:

**If Path B (Production Integration)**:
- [ ] app/llm.py updated with schema corrections
- [ ] Sample questions generate valid SQL
- [ ] 0 schema errors on test questions
- [ ] Documentation updated

**If Path A (Improve Pass Rate)**:
- [ ] Top 10 join pairs documented with confidence
- [ ] Schema files updated
- [ ] Pass rate improved from 15% to 60%+
- [ ] New schema_knowledge.json generated

**If Path C (Expand Coverage)**:
- [ ] 20+ new test questions created
- [ ] Questions cover temporal/aggregation patterns
- [ ] All new questions pass validation

**If Path D (Performance)**:
- [ ] DB connection working
- [ ] 40 queries executed on real data
- [ ] Performance benchmarks documented
- [ ] Slow queries identified and optimized

---

## Questions to Consider

1. What's the priority: production quality or test coverage?
2. Do we have access to the real KCMH database?
3. Should we create a public demo with sample data?
4. How many questions do we want validated before production?

Good luck! 🚀
