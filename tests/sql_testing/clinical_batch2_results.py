"""Clinical Complex Batch 2 Results: CQ011-CQ020"""

CLINICAL_BATCH2_RESPONSES = {
    "CQ011": {
        "needs_clarification": True,
        "clarification_question": "IPT table does not have an age column. To filter by patient age > 70, I would need to join with the PT (patient) table and calculate age from birthdate. Should I proceed with that approach?",
        "sql": """SELECT COUNT(DISTINCT "IPT"."an") AS hip_replacement_count
FROM "KCMH_HIS"."IPT"
INNER JOIN "KCMH_HIS"."IPTSUMOPRT" ON "IPT"."an" = "IPTSUMOPRT"."an"
INNER JOIN "KCMH_HIS"."IPTSUMDIAG" ON "IPT"."an" = "IPTSUMDIAG"."an"
WHERE "IPTSUMOPRT"."icd9cm" IN ('81.51', '81.52')
AND "IPTSUMDIAG"."icd10" LIKE 'M16%'""",
        "assumptions": ["Hip replacement ICD-9-CM 81.51-81.52", "Osteoarthritis M16", "Same admission", "Age filter requires PT table join - not included"],
        "confidence": "medium"
    },
    "CQ012": {
        "needs_clarification": False,
        "sql": """WITH patients_on_aspirin AS (
  SELECT DISTINCT "PRSC"."hn"
  FROM "KCMH_HIS"."PRSC"
  INNER JOIN "KCMH_HIS"."PRSCDT" ON "PRSC"."prscno" = "PRSCDT"."prscno"
  INNER JOIN "KCMH_HIS"."MEDITEMDIS" ON "PRSCDT"."meditem" = "MEDITEMDIS"."meditem"
  WHERE LOWER("MEDITEMDIS"."medname") LIKE '%aspirin%'
),
patients_on_clopidogrel AS (
  SELECT DISTINCT "PRSC"."hn"
  FROM "KCMH_HIS"."PRSC"
  INNER JOIN "KCMH_HIS"."PRSCDT" ON "PRSC"."prscno" = "PRSCDT"."prscno"
  INNER JOIN "KCMH_HIS"."MEDITEMDIS" ON "PRSCDT"."meditem" = "MEDITEMDIS"."meditem"
  WHERE LOWER("MEDITEMDIS"."medname") LIKE '%clopidogrel%'
     OR LOWER("MEDITEMDIS"."tradename") LIKE '%plavix%'
),
dual_antiplatelet_patients AS (
  SELECT a."hn"
  FROM patients_on_aspirin a
  INNER JOIN patients_on_clopidogrel c ON a."hn" = c."hn"
),
gi_bleeding_patients AS (
  SELECT DISTINCT "hn"
  FROM "KCMH_HIS"."PTDIAG"
  WHERE "icd10" >= 'K92.0' AND "icd10" <= 'K92.2'
)
SELECT COUNT(DISTINCT d."hn") AS patient_count_dual_antiplatelet_with_gi_bleeding
FROM dual_antiplatelet_patients d
INNER JOIN gi_bleeding_patients g ON d."hn" = g."hn\"""",
        "assumptions": ["GI bleeding K92.0-K92.2", "Patient must have BOTH aspirin AND clopidogrel", "Dual antiplatelet therapy"],
        "confidence": "medium"
    },
    "CQ013": {
        "needs_clarification": False,
        "sql": """SELECT COUNT(DISTINCT "IPT"."hn") AS patient_count, COUNT(DISTINCT "IPT"."an") AS admission_count
FROM "KCMH_HIS"."IPT"
INNER JOIN "KCMH_HIS"."IPTSUMDIAG" ON "IPT"."an" = "IPTSUMDIAG"."an"
INNER JOIN "KCMH_HIS"."IPTSUMOPRT" ON "IPT"."an" = "IPTSUMOPRT"."an"
INNER JOIN "KCMH_HIS"."LVSTEXM" ON "IPT"."hn" = "LVSTEXM"."hn"
INNER JOIN "KCMH_HIS"."LABEXM" ON "LVSTEXM"."labexm" = "LABEXM"."labexm"
WHERE "IPTSUMDIAG"."icd10" LIKE 'C50%'
AND "IPTSUMOPRT"."icd9cm" BETWEEN '85.41' AND '85.48'
AND ("LABEXM"."name" ILIKE '%estrogen%' OR "LABEXM"."name" ILIKE '%ER%')
AND ("LVSTEXM"."result" ILIKE '%positive%' OR "LVSTEXM"."result" LIKE '%+%')""",
        "assumptions": ["Breast cancer C50", "Mastectomy ICD-9-CM 85.41-85.48", "ER+ via lab result positive"],
        "confidence": "medium"
    },
    "CQ014": {
        "needs_clarification": False,
        "sql": """SELECT COUNT(DISTINCT "PRSC"."hn") AS ckd_patients_on_ace_with_high_k
FROM "KCMH_HIS"."PRSC"
INNER JOIN "KCMH_HIS"."PRSCDT" ON "PRSC"."prscno" = "PRSCDT"."prscno"
INNER JOIN "KCMH_HIS"."MEDITEMDIS" ON "PRSCDT"."meditem" = "MEDITEMDIS"."meditem"
INNER JOIN "KCMH_HIS"."PTDIAG" ON "PRSC"."hn" = "PTDIAG"."hn"
INNER JOIN "KCMH_HIS"."LVSTEXM" ON "PRSC"."hn" = "LVSTEXM"."hn"
INNER JOIN "KCMH_HIS"."LABEXM" ON "LVSTEXM"."labexm" = "LABEXM"."labexm"
WHERE "PTDIAG"."icd10" LIKE 'N18%'
AND (LOWER("MEDITEMDIS"."medname") IN ('enalapril', 'lisinopril', 'ramipril', 'captopril')
     OR LOWER("MEDITEMDIS"."tradename") IN ('enalapril', 'lisinopril', 'ramipril', 'captopril'))
AND (LOWER("LABEXM"."name") LIKE '%potassium%' OR LOWER("LABEXM"."name") LIKE '%k%')
AND CAST("LVSTEXM"."result" AS NUMERIC) > 5.5""",
        "assumptions": ["CKD N18", "ACE inhibitors: enalapril, lisinopril, ramipril, captopril", "Potassium > 5.5"],
        "confidence": "medium"
    },
    "CQ015": {
        "needs_clarification": True,
        "clarification_question": "IPT table does not have an 'admtype' column to distinguish emergency vs elective. The available column 'iptist' (admission status) may not directly indicate this. Would you like me to: 1) Use iptist if it contains this information, or 2) Count all appendectomies without distinguishing type?",
        "sql": """SELECT COUNT(*) as appendectomy_count
FROM "KCMH_HIS"."IPT"
JOIN "KCMH_HIS"."IPTSUMOPRT" ON "IPT"."an" = "IPTSUMOPRT"."an"
WHERE "IPTSUMOPRT"."icd9cm" LIKE '47.0%'
AND EXTRACT(YEAR FROM "IPT"."rgtdate") = 2025""",
        "assumptions": ["Appendectomy ICD-9-CM 47.0", "Year 2025 filter", "Emergency vs Elective distinction not available in schema"],
        "confidence": "low"
    },
    "CQ016": {
        "needs_clarification": True,
        "clarification_question": "This query requires temporal clarification: Should creatinine increase be measured after furosemide start? What timeframe? Comparing first to second result or any pair?",
        "sql": "",
        "assumptions": ["Requires domain clarification on temporal logic"],
        "confidence": "low"
    },
    "CQ017": {
        "needs_clarification": False,
        "sql": """SELECT COUNT(DISTINCT "IPT"."hn") AS patient_count
FROM "KCMH_HIS"."IPT"
INNER JOIN "KCMH_HIS"."IPTSUMOPRT" ON "IPT"."an" = "IPTSUMOPRT"."an"
INNER JOIN "KCMH_HIS"."IPTSUMDIAG" ON "IPT"."an" = "IPTSUMDIAG"."an"
WHERE "IPTSUMOPRT"."icd9cm" IN ('36.06', '36.07')
AND "IPTSUMDIAG"."icd10" LIKE 'I21%'""",
        "assumptions": ["PCI ICD-9-CM 36.06-36.07", "STEMI ICD-10 I21", "Same admission"],
        "confidence": "high"
    },
    "CQ018": {
        "needs_clarification": False,
        "sql": """SELECT COUNT(DISTINCT "PRSC"."hn") AS schizophrenia_patients_on_clozapine_with_low_wbc
FROM "KCMH_HIS"."PRSC"
INNER JOIN "KCMH_HIS"."PRSCDT" ON "PRSC"."prscno" = "PRSCDT"."prscno"
INNER JOIN "KCMH_HIS"."MEDITEMDIS" ON "PRSCDT"."meditem" = "MEDITEMDIS"."meditem"
INNER JOIN "KCMH_HIS"."PTDIAG" ON "PRSC"."hn" = "PTDIAG"."hn"
INNER JOIN "KCMH_HIS"."LVSTEXM" ON "PRSC"."hn" = "LVSTEXM"."hn"
INNER JOIN "KCMH_HIS"."LABEXM" ON "LVSTEXM"."labexm" = "LABEXM"."labexm"
WHERE ("MEDITEMDIS"."medname" ILIKE '%clozapine%' OR "MEDITEMDIS"."tradename" ILIKE '%clozaril%')
AND "PTDIAG"."icd10" LIKE 'F20%'
AND ("LABEXM"."name" ILIKE '%WBC%' OR "LABEXM"."name" ILIKE '%white blood%')
AND CAST("LVSTEXM"."result" AS NUMERIC) < 3000""",
        "assumptions": ["Schizophrenia F20", "Clozapine/Clozaril", "WBC < 3000 threshold"],
        "confidence": "medium"
    },
    "CQ019": {
        "needs_clarification": False,
        "sql": """SELECT COUNT(DISTINCT "IPT"."an") AS pneumonia_with_ventilation_and_positive_bc
FROM "KCMH_HIS"."IPT"
INNER JOIN "KCMH_HIS"."IPTSUMDIAG" ON "IPT"."an" = "IPTSUMDIAG"."an"
INNER JOIN "KCMH_HIS"."IPTSUMOPRT" ON "IPT"."an" = "IPTSUMOPRT"."an"
INNER JOIN "KCMH_HIS"."LVSTEXM" ON "IPT"."hn" = "LVSTEXM"."hn"
INNER JOIN "KCMH_HIS"."LABEXM" ON "LVSTEXM"."labexm" = "LABEXM"."labexm"
WHERE "IPTSUMDIAG"."icd10" >= 'J12' AND "IPTSUMDIAG"."icd10" <= 'J18'
AND "IPTSUMOPRT"."icd9cm" = '96.7'
AND ("LABEXM"."name" ILIKE '%blood culture%' OR "LABEXM"."name" ILIKE '%hemoculture%')
AND ("LVSTEXM"."result" ILIKE '%positive%' OR "LVSTEXM"."result" ILIKE '%growth%')""",
        "assumptions": ["Pneumonia J12-J18", "Mechanical ventilation 96.7", "Blood culture positive"],
        "confidence": "high"
    },
    "CQ020": {
        "needs_clarification": False,
        "sql": """WITH insulin_patients AS (
  SELECT DISTINCT "PRSC"."hn"
  FROM "KCMH_HIS"."PRSC"
  INNER JOIN "KCMH_HIS"."PRSCDT" ON "PRSC"."prscno" = "PRSCDT"."prscno"
  INNER JOIN "KCMH_HIS"."MEDITEMDIS" ON "PRSCDT"."meditem" = "MEDITEMDIS"."meditem"
  WHERE LOWER("MEDITEMDIS"."medname") LIKE '%insulin%'
    OR LOWER("MEDITEMDIS"."medname") LIKE '%novorapid%'
    OR LOWER("MEDITEMDIS"."medname") LIKE '%lantus%'
    OR LOWER("MEDITEMDIS"."medname") LIKE '%humalog%'
),
hypoglycemia_episodes AS (
  SELECT "LVSTEXM"."hn",
         COUNT(*) AS episode_count
  FROM "KCMH_HIS"."LVSTEXM"
  INNER JOIN "KCMH_HIS"."LABEXM" ON "LVSTEXM"."labexm" = "LABEXM"."labexm"
  WHERE (LOWER("LABEXM"."name") LIKE '%glucose%'
    OR LOWER("LABEXM"."name") LIKE '%fbs%')
    AND CAST("LVSTEXM"."result" AS NUMERIC) < 70
  GROUP BY "LVSTEXM"."hn"
  HAVING COUNT(*) >= 2
)
SELECT COUNT(DISTINCT "insulin_patients"."hn") AS patient_count
FROM insulin_patients
INNER JOIN hypoglycemia_episodes ON insulin_patients."hn" = hypoglycemia_episodes."hn\"""",
        "assumptions": ["Insulin/novorapid/lantus/humalog", "Glucose < 70", "Recurrent >= 2 episodes"],
        "confidence": "medium"
    },
}
