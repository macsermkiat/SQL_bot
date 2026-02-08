# Critical Schema Corrections for Production

## Overview
These corrections were discovered during validation of 40 complex clinical SQL queries. Apply these to `app/llm.py` and any schema documentation.

---

## Column Name Corrections

### 1. Prescription Tables (PRSC/PRSCDT/MEDITEMDIS)

**WRONG**:
```sql
-- Using non-existent "meditemdis" column
FROM "KCMH_HIS"."PRSCDT"
JOIN "KCMH_HIS"."MEDITEMDIS" ON PRSCDT.meditemdis = MEDITEMDIS.meditemdis
```

**CORRECT**:
```sql
-- Correct column name is "meditem"
FROM "KCMH_HIS"."PRSCDT"
JOIN "KCMH_HIS"."MEDITEMDIS" ON PRSCDT.meditem = MEDITEMDIS.meditem
```

**Schema Facts**:
- `PRSCDT.meditem` is the FK to drug master (NOT meditemdis)
- `MEDITEMDIS.meditem` is the PK (NOT meditemdis)
- MEDITEMDIS = "Med Item Display" but column is just "meditem"

---

### 2. Procedure Tables (IPTSUMOPRT)

**WRONG**:
```sql
-- Using non-existent "oprdate" column
WHERE EXTRACT(YEAR FROM IPTSUMOPRT.oprdate) = 2025
```

**CORRECT**:
```sql
-- Correct column is "indate" (in-date = procedure date)
WHERE EXTRACT(YEAR FROM IPTSUMOPRT.indate) = 2025
```

**Schema Facts**:
- `IPTSUMOPRT.indate` = procedure start date
- `IPTSUMOPRT.outdate` = procedure end date
- `IPTSUMOPRT.icd9cm` = procedure code

---

### 3. Lab Tables (LVST vs LVSTEXM)

**Critical: These are TWO DIFFERENT tables!**

**LVST** (Lab order header):
- Columns: hn, lvstdate, labgrp, an, dct, ln, labno
- **Does NOT have**: labexm, result
- Purpose: Lab order metadata

**LVSTEXM** (Lab exam results):
- Columns: hn, lvstdate, labexm, result, an, ln, labno
- **Has**: labexm (FK to LABEXM), result
- Purpose: Individual lab test results

**Join Pattern**:
```sql
FROM "KCMH_HIS"."LVSTEXM" lexm
JOIN "KCMH_HIS"."LABEXM" lab ON lexm.labexm = lab.labexm
WHERE LOWER(lab.name) LIKE '%hemoglobin%'
  AND CAST(lexm.result AS NUMERIC) > 10
```

**AVOID**: Using alias `lvst` for LVSTEXM (confuses validators)
**USE**: Explicit aliases like `lexm` or `lvstexm`

---

## Missing Columns (Known Limitations)

### 1. IPT Table Has NO Age Column

**Problem**:
```sql
-- This will FAIL - age column doesn't exist
SELECT * FROM IPT WHERE age > 70
```

**Solution**:
```sql
-- Calculate from birthdate in PT table
SELECT IPT.*,
       EXTRACT(YEAR FROM AGE(CURRENT_DATE, PT.birthdate)) AS age
FROM "KCMH_HIS"."IPT"
JOIN "KCMH_HIS"."PT" ON IPT.hn = PT.hn
WHERE EXTRACT(YEAR FROM AGE(CURRENT_DATE, PT.birthdate)) > 70
```

Or ask for clarification and omit age filter if not critical.

---

### 2. IPT Table Has NO Admission Type Column

**Problem**:
```sql
-- This will FAIL - admtype/iptist doesn't distinguish emergency vs elective
SELECT * FROM IPT WHERE admtype = 'emergency'
```

**Solution**:
- IPT.iptist exists but may not contain emergency/elective distinction
- Ask user for clarification
- Consider alternative: discharge status, diagnosis codes, procedure urgency

---

## Table Alias Best Practices

### Problem: Alias Conflicts with Real Table Names

**BAD**:
```sql
-- "lvst" alias conflicts with LVST table name
FROM "KCMH_HIS"."LVSTEXM" lvst
WHERE lvst.result > 10  -- Validator thinks this is LVST.result (doesn't exist)
```

**GOOD**:
```sql
-- Use explicit alias that doesn't conflict
FROM "KCMH_HIS"."LVSTEXM" lexm
WHERE lexm.result > 10  -- Clear reference to LVSTEXM.result
```

### Known Conflicting Pairs:
- `LVST` vs `LVSTEXM` - Don't use "lvst" as alias for LVSTEXM
- `PT` vs `PTDIAG` - Don't use "pt" as alias for PTDIAG
- `DCT` vs `DCTSPEC` - Don't use "dct" as alias for DCTSPEC

---

## Universal Keys (Always Available for Joins)

These keys link data across the entire system:

1. **hn** (Hospital Number): Patient identifier across all visits
2. **an** (Admission Number): Inpatient admission identifier
3. **vn** (Visit Number): Outpatient visit identifier

**High-Confidence Join Examples**:
```sql
-- Patient diagnosis to lab results
FROM "KCMH_HIS"."PTDIAG" diag
JOIN "KCMH_HIS"."LVSTEXM" lab ON diag.hn = lab.hn

-- Admission to procedures
FROM "KCMH_HIS"."IPT" ipt
JOIN "KCMH_HIS"."IPTSUMOPRT" oprt ON ipt.an = oprt.an

-- Visit to prescriptions
FROM "KCMH_HIS"."OVST" visit
JOIN "KCMH_HIS"."PRSC" prsc ON visit.vn = prsc.vn
```

---

## Common Query Patterns

### 1. Drug + Disease
```sql
WITH drug_patients AS (
  SELECT DISTINCT p.hn
  FROM "KCMH_HIS"."PRSC" p
  JOIN "KCMH_HIS"."PRSCDT" pd ON p.prscno = pd.prscno
  JOIN "KCMH_HIS"."MEDITEMDIS" m ON pd.meditem = m.meditem  -- NOT meditemdis!
  WHERE LOWER(m.medname) LIKE '%metformin%'
),
disease_patients AS (
  SELECT DISTINCT hn
  FROM "KCMH_HIS"."PTDIAG"
  WHERE icd10 >= 'E10' AND icd10 <= 'E14'
)
SELECT COUNT(DISTINCT dp.hn)
FROM drug_patients dp
JOIN disease_patients dis ON dp.hn = dis.hn
```

### 2. Procedure + Diagnosis (Same Admission)
```sql
SELECT COUNT(DISTINCT ipt.an)
FROM "KCMH_HIS"."IPT" ipt
JOIN "KCMH_HIS"."IPTSUMOPRT" oprt ON ipt.an = oprt.an
JOIN "KCMH_HIS"."IPTSUMDIAG" diag ON ipt.an = diag.an
WHERE oprt.icd9cm = '36.06'  -- PCI
  AND diag.icd10 LIKE 'I21%'  -- STEMI
```

### 3. Drug + Lab Result
```sql
WITH drug_patients AS (
  SELECT DISTINCT p.hn
  FROM "KCMH_HIS"."PRSC" p
  JOIN "KCMH_HIS"."PRSCDT" pd ON p.prscno = pd.prscno
  JOIN "KCMH_HIS"."MEDITEMDIS" m ON pd.meditem = m.meditem
  WHERE LOWER(m.medname) LIKE '%warfarin%'
),
lab_results AS (
  SELECT DISTINCT lexm.hn
  FROM "KCMH_HIS"."LVSTEXM" lexm  -- NOT lvst!
  JOIN "KCMH_HIS"."LABEXM" lab ON lexm.labexm = lab.labexm
  WHERE LOWER(lab.name) LIKE '%inr%'
    AND CAST(lexm.result AS NUMERIC) > 4.0
)
SELECT COUNT(DISTINCT dp.hn)
FROM drug_patients dp
JOIN lab_results lr ON dp.hn = lr.hn
```

---

## Integration Checklist for app/llm.py

When updating the main SQL generation prompt:

- [ ] Add PRSCDT.meditem (NOT meditemdis) to schema context
- [ ] Add MEDITEMDIS.meditem as PK (NOT meditemdis)
- [ ] Add IPTSUMOPRT.indate (NOT oprdate) for procedure dates
- [ ] Clarify LVST vs LVSTEXM distinction
- [ ] Warn about IPT missing age/admtype columns
- [ ] Add table alias guidance (avoid conflicts)
- [ ] Include universal keys (hn, an, vn) prominently
- [ ] Add common join patterns as examples

---

## Testing Verification

After applying these corrections, verify with:

```bash
cd "/Users/admin/Project_Chatbot_research/SQL bot"
python -m tests.sql_testing.run_clinical_batches
```

Expected result: **100% pass+warn rate** (0 failures)

Current results (with corrections applied):
- Total: 40 questions
- Passed: 6 (15.0%)
- Warned: 34 (85.0%)
- Failed: 0 (0.0%)
- Pass+Warn: 100.0% ✓
