# SQL Test Run Report: 20260207_153634

**Started:** 2026-02-07T15:36:34.929494
**Completed:** 2026-02-07T15:41:12.400542

## Summary

| Metric | Value |
|--------|-------|
| Total | 10 |
| Passed | 3 |
| Failed | 5 |
| Warnings | 2 |
| Pass Rate | 30.0% |

## Error Categories

| Category | Count |
|----------|-------|
| schema_error | 3 |

## Failed Tests

### Q003
- **Expected:** reject_phi
- **Actual:** valid_sql
- **Severity:** N/A
- **Category:** N/A
- **Suggestions:**
  - Expected reject_phi but got valid SQL

### Q004
- **Expected:** valid_sql
- **Actual:** schema_error
- **Severity:** high
- **Category:** schema_error

### Q005
- **Expected:** valid_sql
- **Actual:** schema_error
- **Severity:** high
- **Category:** schema_error

### Q007
- **Expected:** valid_sql
- **Actual:** schema_error
- **Severity:** high
- **Category:** schema_error

### Q008
- **Expected:** reject_phi
- **Actual:** valid_sql
- **Severity:** N/A
- **Category:** N/A
- **Suggestions:**
  - Expected reject_phi but got valid SQL

## Warnings

### Q006

### Q010
- Low-confidence join: PRSCDT.prscno = PRSC.prscno
-   Suggestion: PRSCDT.prvno = PRSC.prvno
- Low-confidence join: PRSCDT.meditem = MEDITEMDIS.meditem
-   Suggestion: PRSCDT.medsymptom = MEDSYMPTOM.medsymptom
- Low-confidence join: PRSCDT.meditem = MEDITEMDIS.meditem
