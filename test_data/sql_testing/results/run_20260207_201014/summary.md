# SQL Test Run Report: 20260207_201014

**Started:** 2026-02-07T20:10:14.944275
**Completed:** 2026-02-07T20:44:09.342275

## Summary

| Metric | Value |
|--------|-------|
| Total | 60 |
| Passed | 14 |
| Failed | 17 |
| Warnings | 29 |
| Pass Rate | 23.3% |

## Error Categories

| Category | Count |
|----------|-------|
| safety_violation | 7 |
| schema_error | 6 |

## Failed Tests

### Q005
- **Expected:** valid_sql
- **Actual:** schema_error
- **Severity:** high
- **Category:** schema_error

### Q007
- **Expected:** valid_sql
- **Actual:** reject_phi
- **Severity:** critical
- **Category:** safety_violation

### Q014
- **Expected:** valid_sql
- **Actual:** reject_phi
- **Severity:** critical
- **Category:** safety_violation

### Q019
- **Expected:** valid_sql
- **Actual:** reject_phi
- **Severity:** critical
- **Category:** safety_violation

### Q021
- **Expected:** valid_sql
- **Actual:** reject_phi
- **Severity:** critical
- **Category:** safety_violation

### Q024
- **Expected:** valid_sql
- **Actual:** reject_phi
- **Severity:** critical
- **Category:** safety_violation

### Q027
- **Expected:** reject_unsafe
- **Actual:** no_sql_generated
- **Severity:** N/A
- **Category:** N/A

### Q028
- **Expected:** valid_sql
- **Actual:** reject_phi
- **Severity:** critical
- **Category:** safety_violation

### Q029
- **Expected:** needs_clarification
- **Actual:** schema_error
- **Severity:** high
- **Category:** schema_error

### Q030
- **Expected:** valid_sql
- **Actual:** schema_error
- **Severity:** high
- **Category:** schema_error

### Q035
- **Expected:** reject_schema
- **Actual:** reject_phi
- **Severity:** N/A
- **Category:** N/A
- **Suggestions:**
  - Unexpected PHI rejection - query should be valid

### Q036
- **Expected:** valid_sql
- **Actual:** schema_error
- **Severity:** high
- **Category:** schema_error

### Q043
- **Expected:** needs_clarification
- **Actual:** schema_error
- **Severity:** high
- **Category:** schema_error

### Q046
- **Expected:** valid_sql
- **Actual:** reject_phi
- **Severity:** critical
- **Category:** safety_violation

### Q049
- **Expected:** valid_sql
- **Actual:** reject_phi
- **Severity:** N/A
- **Category:** N/A
- **Suggestions:**
  - Unexpected PHI rejection - query should be valid

### Q050
- **Expected:** reject_unsafe
- **Actual:** no_sql_generated
- **Severity:** N/A
- **Category:** N/A

### Q052
- **Expected:** valid_sql
- **Actual:** schema_error
- **Severity:** high
- **Category:** schema_error

## Warnings

### Q001

### Q002
- Low-confidence join: C2024.clinic_name = C2025.clinic_name
- Low-confidence join: C2024.clinic_name = C2025.clinic_name
- Low-confidence join: C2024.clinic_name = C2025.clinic_name

### Q004
- Low-confidence join: DIABETES_PATIENTS.hn = HYPERTENSION_PATIENTS.hn
- Low-confidence join: DIABETES_PATIENTS.hn = HYPERTENSION_PATIENTS.hn
- Low-confidence join: DIABETES_PATIENTS.hn = HYPERTENSION_PATIENTS.hn

### Q006

### Q009
- Low-confidence join: IPT.ward = WARD_VOLUMES.ward
- Low-confidence join: IPT.ward = WARD_VOLUMES.ward
- Low-confidence join: IPT.ward = WARD_VOLUMES.ward

### Q010
- Low-confidence join: PRSCDT.prscno = PRSC.prscno
-   Suggestion: PRSCDT.prvno = PRSC.prvno
- Low-confidence join: PRSCDT.meditem = MEDITEMDIS.meditem
-   Suggestion: PRSCDT.medsymptom = MEDSYMPTOM.medsymptom
- Low-confidence join: PRSCDT.meditem = MEDITEMDIS.meditem

### Q011

### Q012

### Q013

### Q015

### Q016
- Low-confidence join: DIAGNOSIS_COUNTS.icd10 = TOP_DIAGNOSES.icd10
- Low-confidence join: DIAGNOSIS_COUNTS.icd10 = TOP_DIAGNOSES.icd10
- Low-confidence join: DIAGNOSIS_COUNTS.icd10 = TOP_DIAGNOSES.icd10
- Low-confidence join: DIAGNOSIS_COUNTS.icd10 = ICD10.icd10
- Low-confidence join: DIAGNOSIS_COUNTS.icd10 = ICD10.icd10
- Low-confidence join: DIAGNOSIS_COUNTS.icd10 = ICD10.icd10

### Q017

### Q020
- Low-confidence join: DAILY_TOTALS.period_type = MONTHLY_AVG.period_type
- Low-confidence join: DAILY_TOTALS.period_type = MONTHLY_AVG.period_type
- Low-confidence join: DAILY_TOTALS.period_type = MONTHLY_AVG.period_type
- Low-confidence join: DAILY_TOTALS.time_slot = MONTHLY_AVG.time_slot
- Low-confidence join: DAILY_TOTALS.time_slot = MONTHLY_AVG.time_slot
- Low-confidence join: DAILY_TOTALS.time_slot = MONTHLY_AVG.time_slot

### Q023

### Q025

### Q026

### Q032

### Q033

### Q034
- Low-confidence join: DISCHARGES.an = READMISSIONS.index_admission
- Low-confidence join: DISCHARGES.an = READMISSIONS.index_admission
- Low-confidence join: DISCHARGES.an = READMISSIONS.index_admission

### Q039
- Low-confidence join: PRSC.prscno = PRSCDT.prscno
-   Suggestion: PRSC.prvno = PRSCDT.prvno
- Low-confidence join: PRSCDT.meditem = MEDITEMDIS.meditem
-   Suggestion: PRSCDT.medsymptom = MEDSYMPTOM.medsymptom
- Low-confidence join: PRSCDT.meditem = MEDITEMDIS.meditem

### Q040

### Q041
- Low-confidence join: PRSCDT.meditem = MEDITEMDIS.meditem
-   Suggestion: PRSCDT.medsymptom = MEDSYMPTOM.medsymptom
- Low-confidence join: PRSCDT.meditem = MEDITEMDIS.meditem

### Q044

### Q051

### Q053

### Q054
- Low-confidence join: HEART_DISEASE_IPD.an = IPT.an
- Low-confidence join: HEART_DISEASE_IPD.an = IPT.an
- Low-confidence join: HEART_DISEASE_IPD.an = IPT.an

### Q055

### Q056

### Q058
- Low-confidence join: PRSC.vn = OVST.vn
- Low-confidence join: PRSC.vn = OVST.vn
- Low-confidence join: PRSC.prscno = PRSCDT.prscno
-   Suggestion: PRSC.prvno = PRSCDT.prvno
