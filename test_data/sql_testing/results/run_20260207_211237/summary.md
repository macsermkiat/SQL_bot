# SQL Test Run Report: 20260207_211237

**Started:** 2026-02-07T21:12:37.947550
**Completed:** 2026-02-07T21:20:08.524776

## Summary

| Metric | Value |
|--------|-------|
| Total | 15 |
| Passed | 3 |
| Failed | 2 |
| Warnings | 10 |
| Pass Rate | 20.0% |

## Error Categories

| Category | Count |
|----------|-------|
| safety_violation | 1 |
| schema_error | 1 |

## Failed Tests

### Q046
- **Expected:** valid_sql
- **Actual:** reject_phi
- **Severity:** critical
- **Category:** safety_violation

### Q043
- **Expected:** needs_clarification
- **Actual:** schema_error
- **Severity:** high
- **Category:** schema_error

## Warnings

### Q056

### Q006

### Q034
- Low-confidence join: INDEX_ADMISSIONS.index_an = READMISSIONS.index_an
- Low-confidence join: INDEX_ADMISSIONS.index_an = READMISSIONS.index_an
- Low-confidence join: INDEX_ADMISSIONS.index_an = READMISSIONS.index_an
- Low-confidence join: INDEX_ADMISSIONS.hn = IPT.hn
- Low-confidence join: INDEX_ADMISSIONS.hn = IPT.hn
- Low-confidence join: INDEX_ADMISSIONS.hn = IPT.hn

### Q010
- Low-confidence join: PRSC.prscno = PRSCDT.prscno
-   Suggestion: PRSC.prvno = PRSCDT.prvno
- Low-confidence join: PRSCDT.meditem = MEDITEMDIS.meditem
-   Suggestion: PRSCDT.medsymptom = MEDSYMPTOM.medsymptom
- Low-confidence join: PRSCDT.meditem = MEDITEMDIS.meditem

### Q026

### Q023

### Q015

### Q004
- Low-confidence join: DIABETES.hn = HYPERTENSION.hn
- Low-confidence join: DIABETES.hn = HYPERTENSION.hn
- Low-confidence join: DIABETES.hn = HYPERTENSION.hn

### Q017
- Low-confidence join: PTDIAG.vn = OVST.vn
- Low-confidence join: PTDIAG.vn = OVST.vn

### Q053
