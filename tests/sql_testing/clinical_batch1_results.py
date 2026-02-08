"""Clinical Complex Batch 1 Results: CQ001-CQ010"""

CLINICAL_BATCH1_RESPONSES = {
    "CQ001": {
        "needs_clarification": False,
        "sql": """WITH phenytoin_patients AS (
  SELECT DISTINCT "KCMH_HIS"."PRSC"."hn"
  FROM "KCMH_HIS"."PRSC"
  JOIN "KCMH_HIS"."PRSCDT" ON "KCMH_HIS"."PRSC"."prscno" = "KCMH_HIS"."PRSCDT"."prscno"
  JOIN "KCMH_HIS"."MEDITEMDIS" ON "KCMH_HIS"."PRSCDT"."meditem" = "KCMH_HIS"."MEDITEMDIS"."meditem"
  WHERE (LOWER("KCMH_HIS"."MEDITEMDIS"."medname") LIKE '%phenytoin%' OR LOWER("KCMH_HIS"."MEDITEMDIS"."tradename") LIKE '%dilantin%')
  AND EXTRACT(YEAR FROM "KCMH_HIS"."PRSC"."prscdate") = EXTRACT(YEAR FROM CURRENT_DATE) - 1
),
hepatitis_patients AS (
  SELECT DISTINCT "KCMH_HIS"."PTDIAG"."hn"
  FROM "KCMH_HIS"."PTDIAG"
  WHERE "KCMH_HIS"."PTDIAG"."icd10" >= 'B15' AND "KCMH_HIS"."PTDIAG"."icd10" <= 'B19'
)
SELECT COUNT(*) AS patient_count
FROM phenytoin_patients
WHERE "hn" IN (SELECT "hn" FROM hepatitis_patients)""",
        "assumptions": ["Phenytoin search via medname/tradename", "Hepatitis ICD-10 B15-B19", "Last year filter"],
        "confidence": "medium"
    },
    "CQ002": {
        "needs_clarification": False,
        "sql": """SELECT COUNT(DISTINCT p.hn) AS patient_count
FROM "KCMH_HIS"."PRSC" p
INNER JOIN "KCMH_HIS"."PRSCDT" pd ON p.prscno = pd.prscno
INNER JOIN "KCMH_HIS"."MEDITEMDIS" m ON pd.meditem = m.meditem
INNER JOIN (
  SELECT hn, result, labexm, lvstdate, ROW_NUMBER() OVER (PARTITION BY hn ORDER BY lvstdate DESC) AS rn
  FROM "KCMH_HIS"."LVSTEXM"
  WHERE labexm IN (SELECT labexm FROM "KCMH_HIS"."LABEXM" WHERE LOWER(name) LIKE '%ldl%')
) ldl ON p.hn = ldl.hn AND ldl.rn = 1
WHERE (LOWER(m.medname) LIKE '%atorvastatin%' OR LOWER(m.tradename) LIKE '%lipitor%')
AND CAST(ldl.result AS NUMERIC) > 190""",
        "assumptions": ["Most recent LDL via ROW_NUMBER", "Atorvastatin/Lipitor search", "LDL > 190 threshold"],
        "confidence": "medium"
    },
    "CQ003": {
        "needs_clarification": False,
        "sql": """SELECT COUNT(DISTINCT "KCMH_HIS"."IPT"."hn") AS patient_count
FROM "KCMH_HIS"."IPT"
INNER JOIN "KCMH_HIS"."IPTSUMOPRT" ON "KCMH_HIS"."IPT"."an" = "KCMH_HIS"."IPTSUMOPRT"."an"
INNER JOIN "KCMH_HIS"."IPTSUMDIAG" ON "KCMH_HIS"."IPT"."an" = "KCMH_HIS"."IPTSUMDIAG"."an"
WHERE EXTRACT(YEAR FROM "KCMH_HIS"."IPTSUMOPRT"."indate") = EXTRACT(YEAR FROM CURRENT_DATE) - 1
AND "KCMH_HIS"."IPTSUMOPRT"."icd9cm" = '01.24'
AND "KCMH_HIS"."IPTSUMDIAG"."icd10" LIKE 'D32%'""",
        "assumptions": ["Craniotomy ICD-9-CM 01.24", "Meningioma ICD-10 D32", "Same admission join via an"],
        "confidence": "high"
    },
    "CQ004": {
        "needs_clarification": False,
        "sql": """WITH warfarin_patients AS (
  SELECT DISTINCT "KCMH_HIS"."PRSC"."hn"
  FROM "KCMH_HIS"."PRSC"
  INNER JOIN "KCMH_HIS"."PRSCDT" ON "KCMH_HIS"."PRSC"."prscno" = "KCMH_HIS"."PRSCDT"."prscno"
  INNER JOIN "KCMH_HIS"."MEDITEMDIS" ON "KCMH_HIS"."PRSCDT"."meditem" = "KCMH_HIS"."MEDITEMDIS"."meditem"
  WHERE (LOWER("KCMH_HIS"."MEDITEMDIS"."medname") LIKE '%warfarin%' OR LOWER("KCMH_HIS"."MEDITEMDIS"."tradename") LIKE '%coumadin%')
  AND "KCMH_HIS"."PRSC"."prscdate" >= (CURRENT_DATE - INTERVAL '3 months')
),
inr_tests AS (
  SELECT "KCMH_HIS"."LVSTEXM"."hn"
  FROM "KCMH_HIS"."LVSTEXM"
  INNER JOIN "KCMH_HIS"."LABEXM" ON "KCMH_HIS"."LVSTEXM"."labexm" = "KCMH_HIS"."LABEXM"."labexm"
  WHERE LOWER("KCMH_HIS"."LABEXM"."name") LIKE '%inr%'
  AND CAST("KCMH_HIS"."LVSTEXM"."result" AS NUMERIC) > 4.0
  AND "KCMH_HIS"."LVSTEXM"."lvstdate" >= (CURRENT_DATE - INTERVAL '3 months')
)
SELECT COUNT(DISTINCT warfarin_patients."hn") AS patient_count
FROM warfarin_patients
INNER JOIN inr_tests ON warfarin_patients."hn" = inr_tests."hn\"""",
        "assumptions": ["Warfarin/Coumadin search", "INR > 4.0 threshold", "3 month timeframe"],
        "confidence": "medium"
    },
    "CQ005": {
        "needs_clarification": False,
        "sql": """WITH metformin_patients AS (
  SELECT DISTINCT p.hn
  FROM "KCMH_HIS"."PRSC" p
  JOIN "KCMH_HIS"."PRSCDT" pd ON p.prscno = pd.prscno
  JOIN "KCMH_HIS"."MEDITEMDIS" m ON pd.meditem = m.meditem
  WHERE LOWER(m.medname) LIKE '%metformin%'
),
diabetic_patients AS (
  SELECT DISTINCT ptd.hn
  FROM "KCMH_HIS"."PTDIAG" ptd
  WHERE ptd.icd10 >= 'E10' AND ptd.icd10 <= 'E14'
),
last_hba1c AS (
  SELECT DISTINCT ON (l.hn) l.hn, l.result, l.lvstdate
  FROM "KCMH_HIS"."LVSTEXM" l
  JOIN "KCMH_HIS"."LABEXM" le ON l.labexm = le.labexm
  WHERE le.name ILIKE '%HbA1c%' OR le.name ILIKE '%A1C%'
  ORDER BY l.hn, l.lvstdate DESC
)
SELECT COUNT(DISTINCT m.hn) AS poorly_controlled_diabetic_count
FROM metformin_patients m
JOIN diabetic_patients d ON m.hn = d.hn
JOIN last_hba1c h ON m.hn = h.hn
WHERE CAST(h.result AS NUMERIC) > 9.0""",
        "assumptions": ["Triple join: drug + diagnosis + lab", "HbA1c > 9% threshold", "Most recent HbA1c via DISTINCT ON"],
        "confidence": "medium"
    },
    "CQ006": {
        "needs_clarification": False,
        "sql": """WITH cabg_patients AS (
  SELECT DISTINCT ipt.an, ipt.hn
  FROM "KCMH_HIS"."IPT" ipt
  INNER JOIN "KCMH_HIS"."IPTSUMOPRT" oprt ON ipt.an = oprt.an
  WHERE oprt.icd9cm LIKE '36.1%'
    AND EXTRACT(YEAR FROM ipt.rgtdate) = 2025
),
diabetes_patients AS (
  SELECT DISTINCT an FROM "KCMH_HIS"."IPTSUMDIAG"
  WHERE icd10 >= 'E10' AND icd10 <= 'E14'
),
hypertension_patients AS (
  SELECT DISTINCT an FROM "KCMH_HIS"."IPTSUMDIAG"
  WHERE icd10 >= 'I10' AND icd10 <= 'I15'
)
SELECT COUNT(DISTINCT cp.an) AS cabg_surgeries_count
FROM cabg_patients cp
WHERE cp.an IN (SELECT an FROM diabetes_patients)
  AND cp.an IN (SELECT an FROM hypertension_patients)""",
        "assumptions": ["CABG ICD-9-CM 36.1x", "Both DM and HTN required", "Same admission"],
        "confidence": "high"
    },
    "CQ007": {
        "needs_clarification": False,
        "sql": """WITH amiodarone_patients AS (
  SELECT DISTINCT p.hn
  FROM "KCMH_HIS"."PRSC" p
  JOIN "KCMH_HIS"."PRSCDT" pd ON p.prscno = pd.prscno
  JOIN "KCMH_HIS"."MEDITEMDIS" m ON pd.meditem = m.meditem
  WHERE LOWER(m.medname) LIKE '%amiodarone%' OR LOWER(m.tradename) LIKE '%cordarone%'
),
tsh_abnormal AS (
  SELECT DISTINCT l.hn
  FROM "KCMH_HIS"."LVSTEXM" l
  JOIN "KCMH_HIS"."LABEXM" le ON l.labexm = le.labexm
  WHERE LOWER(le.name) LIKE '%tsh%'
    AND (CAST(l.result AS NUMERIC) < 0.4 OR CAST(l.result AS NUMERIC) > 4.0)
)
SELECT COUNT(DISTINCT ap.hn) AS patient_count
FROM amiodarone_patients ap
INNER JOIN tsh_abnormal ta ON ap.hn = ta.hn""",
        "assumptions": ["Amiodarone/Cordarone search", "TSH < 0.4 or > 4.0 abnormal", "Adverse drug reaction pattern"],
        "confidence": "medium"
    },
    "CQ008": {
        "needs_clarification": False,
        "sql": """SELECT COUNT(DISTINCT "KCMH_HIS"."IPT"."hn") AS patient_count
FROM "KCMH_HIS"."IPT"
INNER JOIN "KCMH_HIS"."IPTSUMOPRT" ON "KCMH_HIS"."IPT"."an" = "KCMH_HIS"."IPTSUMOPRT"."an"
INNER JOIN "KCMH_HIS"."IPTSUMDIAG" ON "KCMH_HIS"."IPT"."an" = "KCMH_HIS"."IPTSUMDIAG"."an"
WHERE "KCMH_HIS"."IPTSUMOPRT"."icd9cm" IN ('51.22', '51.23')
AND "KCMH_HIS"."IPTSUMDIAG"."icd10" = 'K81.0'""",
        "assumptions": ["Cholecystectomy ICD-9-CM 51.22/51.23", "Acute cholecystitis K81.0", "Same admission"],
        "confidence": "high"
    },
    "CQ009": {
        "needs_clarification": False,
        "sql": """WITH epilepsy_patients AS (
  SELECT DISTINCT "KCMH_HIS"."PTDIAG"."hn"
  FROM "KCMH_HIS"."PTDIAG"
  WHERE "KCMH_HIS"."PTDIAG"."icd10" LIKE 'G40%' OR "KCMH_HIS"."PTDIAG"."icd10" LIKE 'G41%'
),
carbamazepine_users AS (
  SELECT DISTINCT "KCMH_HIS"."PRSC"."hn"
  FROM "KCMH_HIS"."PRSC"
  INNER JOIN "KCMH_HIS"."PRSCDT" ON "KCMH_HIS"."PRSC"."prscno" = "KCMH_HIS"."PRSCDT"."prscno"
  INNER JOIN "KCMH_HIS"."MEDITEMDIS" ON "KCMH_HIS"."PRSCDT"."meditem" = "KCMH_HIS"."MEDITEMDIS"."meditem"
  WHERE LOWER("KCMH_HIS"."MEDITEMDIS"."medname") LIKE '%carbamazepine%' OR LOWER("KCMH_HIS"."MEDITEMDIS"."tradename") LIKE '%tegretol%'
),
low_sodium AS (
  SELECT DISTINCT "KCMH_HIS"."LVSTEXM"."hn"
  FROM "KCMH_HIS"."LVSTEXM"
  INNER JOIN "KCMH_HIS"."LABEXM" ON "KCMH_HIS"."LVSTEXM"."labexm" = "KCMH_HIS"."LABEXM"."labexm"
  WHERE LOWER("KCMH_HIS"."LABEXM"."name") LIKE '%sodium%'
    AND CAST("KCMH_HIS"."LVSTEXM"."result" AS NUMERIC) < 130
)
SELECT COUNT(DISTINCT epilepsy_patients."hn") AS patient_count
FROM epilepsy_patients
INNER JOIN carbamazepine_users ON epilepsy_patients."hn" = carbamazepine_users."hn"
INNER JOIN low_sodium ON epilepsy_patients."hn" = low_sodium."hn\"""",
        "assumptions": ["Triple join: diagnosis + drug + lab", "Epilepsy G40-G41", "Carbamazepine/Tegretol", "Sodium < 130"],
        "confidence": "medium"
    },
    "CQ010": {
        "needs_clarification": False,
        "sql": """SELECT COUNT(DISTINCT "KCMH_HIS"."PRSC"."hn") AS patient_count
FROM "KCMH_HIS"."PRSC"
INNER JOIN "KCMH_HIS"."PRSCDT" ON "KCMH_HIS"."PRSC"."prscno" = "KCMH_HIS"."PRSCDT"."prscno"
INNER JOIN "KCMH_HIS"."MEDITEMDIS" ON "KCMH_HIS"."PRSCDT"."meditem" = "KCMH_HIS"."MEDITEMDIS"."meditem"
INNER JOIN "KCMH_HIS"."LVSTEXM" ON "KCMH_HIS"."PRSC"."hn" = "KCMH_HIS"."LVSTEXM"."hn"
INNER JOIN "KCMH_HIS"."LABEXM" ON "KCMH_HIS"."LVSTEXM"."labexm" = "KCMH_HIS"."LABEXM"."labexm"
WHERE LOWER("KCMH_HIS"."MEDITEMDIS"."medname") LIKE '%methotrexate%'
AND (LOWER("KCMH_HIS"."LABEXM"."name") LIKE '%alt%' OR LOWER("KCMH_HIS"."LABEXM"."name") LIKE '%sgpt%')
AND CAST("KCMH_HIS"."LVSTEXM"."result" AS NUMERIC) > 120
AND "KCMH_HIS"."LVSTEXM"."lvstdate" >= "KCMH_HIS"."PRSC"."prscdate\"""",
        "assumptions": ["Methotrexate search", "ALT/SGPT > 120 (3x ULN)", "Lab after prescription date"],
        "confidence": "medium"
    },
}
