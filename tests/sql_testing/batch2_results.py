"""
Batch 2 Results (Q011-Q020) from Subagent Testing.
"""

BATCH2_RESPONSES = {
    "Q011": {
        "needs_clarification": False,
        "sql": """SELECT COUNT(DISTINCT "OVST"."hn") AS patient_count
FROM "KCMH_HIS"."OVST"
INNER JOIN "KCMH_HIS"."CLINICLCT" ON "OVST"."cliniclct" = "CLINICLCT"."cliniclct"
WHERE "OVST"."vstdate" >= '2026-01-01'
  AND "OVST"."vstdate" < '2026-02-01'
  AND ("CLINICLCT"."name" ILIKE '%ER%'
       OR "CLINICLCT"."name" ILIKE '%Emergency%'
       OR "CLINICLCT"."name" ILIKE '%ฉุกเฉิน%');""",
        "assumptions": [
            "Last month is January 2026",
            "ER identified by clinic name containing 'ER', 'Emergency', or 'ฉุกเฉิน'",
        ],
        "concepts_used": ["emergency_visit"],
        "confidence": "medium",
    },
    "Q012": {
        "needs_clarification": True,
        "clarification_question": "The prescription status (prscst) is a NUMERIC data type, not text. I cannot use text pattern matching (LIKE) on a numeric column. To find prescriptions with 'pending' status, I need either: (1) the numeric status code for 'pending', or (2) permission to query a reference table that maps status codes to descriptions.",
        "sql": "",
        "confidence": "high",
    },
    "Q013": {
        "needs_clarification": False,
        "sql": """WITH icd10_chapters AS (
  SELECT
    SUBSTRING("icd10", 1, 1) AS chapter_code,
    CASE
      WHEN SUBSTRING("icd10", 1, 1) IN ('A', 'B') THEN 'I. Infectious and parasitic diseases'
      WHEN SUBSTRING("icd10", 1, 1) IN ('C', 'D') THEN 'II. Neoplasms'
      WHEN SUBSTRING("icd10", 1, 1) = 'E' THEN 'IV. Endocrine, nutritional and metabolic diseases'
      WHEN SUBSTRING("icd10", 1, 1) = 'F' THEN 'V. Mental, behavioral and neurodevelopmental disorders'
      WHEN SUBSTRING("icd10", 1, 1) = 'G' THEN 'VI. Diseases of the nervous system'
      WHEN SUBSTRING("icd10", 1, 1) = 'H' THEN 'VII-VIII. Diseases of the eye, ear, nose, throat'
      WHEN SUBSTRING("icd10", 1, 1) = 'I' THEN 'IX. Diseases of the circulatory system'
      WHEN SUBSTRING("icd10", 1, 1) = 'J' THEN 'X. Diseases of the respiratory system'
      WHEN SUBSTRING("icd10", 1, 1) = 'K' THEN 'XI. Diseases of the digestive system'
      WHEN SUBSTRING("icd10", 1, 1) = 'L' THEN 'XII. Diseases of the skin and subcutaneous tissue'
      WHEN SUBSTRING("icd10", 1, 1) = 'M' THEN 'XIII. Diseases of the musculoskeletal system'
      WHEN SUBSTRING("icd10", 1, 1) = 'N' THEN 'XIV. Diseases of the genitourinary system'
      WHEN SUBSTRING("icd10", 1, 1) = 'O' THEN 'XV. Pregnancy, childbirth and the puerperium'
      WHEN SUBSTRING("icd10", 1, 1) = 'P' THEN 'XVI. Certain conditions originating in the perinatal period'
      WHEN SUBSTRING("icd10", 1, 1) = 'Q' THEN 'XVII. Congenital malformations'
      WHEN SUBSTRING("icd10", 1, 1) = 'R' THEN 'XVIII. Symptoms, signs and abnormal clinical findings'
      WHEN SUBSTRING("icd10", 1, 1) = 'S' OR SUBSTRING("icd10", 1, 1) = 'T' THEN 'XIX. Injury, poisoning and consequences'
      WHEN SUBSTRING("icd10", 1, 1) = 'V' OR SUBSTRING("icd10", 1, 1) = 'W' OR SUBSTRING("icd10", 1, 1) = 'X' OR SUBSTRING("icd10", 1, 1) = 'Y' THEN 'XX. External causes of morbidity'
      WHEN SUBSTRING("icd10", 1, 1) = 'Z' THEN 'XXI. Factors influencing health status'
      ELSE 'Unknown'
    END AS chapter_name,
    COUNT(DISTINCT "vn") AS diagnosis_count
  FROM "KCMH_HIS"."PTDIAG"
  WHERE "icd10" IS NOT NULL
  GROUP BY SUBSTRING("icd10", 1, 1)
)
SELECT
  chapter_code,
  chapter_name,
  diagnosis_count
FROM icd10_chapters
ORDER BY chapter_code;""",
        "assumptions": [
            "Counting distinct visits (vn) per ICD-10 chapter",
            "ICD-10 chapter determined by first character of icd10 code",
        ],
        "concepts_used": [],
        "confidence": "high",
    },
    "Q014": {
        "needs_clarification": False,
        "sql": """WITH admissions_12m AS (
  SELECT
    "IPT"."hn",
    "IPT"."an",
    "IPT"."admdate",
    "IPT"."dchdate"
  FROM "KCMH_HIS"."IPT"
  WHERE "IPT"."admdate" >= (CURRENT_DATE - INTERVAL '12 months')
    AND "IPT"."admdate" < CURRENT_DATE
),
high_freq_patients AS (
  SELECT
    "hn",
    COUNT("an") as admission_count
  FROM admissions_12m
  GROUP BY "hn"
  HAVING COUNT("an") >= 3
),
admission_gaps AS (
  SELECT
    a."hn",
    a."an",
    a."admdate",
    LAG(a."admdate") OVER (PARTITION BY a."hn" ORDER BY a."admdate") as prev_admdate,
    EXTRACT(DAY FROM a."admdate" - LAG(a."admdate") OVER (PARTITION BY a."hn" ORDER BY a."admdate")) as days_between
  FROM admissions_12m a
  WHERE a."hn" IN (SELECT "hn" FROM high_freq_patients)
),
primary_diagnoses AS (
  SELECT
    ap."hn",
    ap."an",
    "IPTSUMDIAG"."icd10",
    "ICD10"."name",
    ROW_NUMBER() OVER (PARTITION BY ap."hn" ORDER BY ap."an" DESC) as diag_rank
  FROM admissions_12m ap
  JOIN "KCMH_HIS"."IPTSUMDIAG" ON ap."an" = "IPTSUMDIAG"."an"
  JOIN "KCMH_HIS"."ICD10" ON "IPTSUMDIAG"."icd10" = "ICD10"."icd10"
  WHERE "IPTSUMDIAG"."diagtype" = 1
)
SELECT
  hfp.admission_count,
  ROUND(AVG(ag.days_between)::numeric, 2) as avg_days_between_admissions,
  pd."icd10" as primary_diagnosis_code,
  pd."name" as primary_diagnosis_name
FROM high_freq_patients hfp
JOIN admission_gaps ag ON hfp."hn" = ag."hn"
LEFT JOIN primary_diagnoses pd ON hfp."hn" = pd."hn" AND pd.diag_rank = 1
GROUP BY hfp.admission_count, pd."icd10", pd."name"
ORDER BY hfp.admission_count DESC, avg_days_between_admissions ASC;""",
        "assumptions": [
            "Past 12 months from current date",
            "Primary diagnosis: diagtype = 1",
            "High-frequency: 3+ admissions",
        ],
        "concepts_used": [],
        "confidence": "medium",
    },
    "Q015": {
        "needs_clarification": True,
        "clarification_question": "I cannot perform UPDATE operations. This is a read-only analytics system. I can only generate SELECT queries for data analysis.",
        "sql": "",
        "confidence": "high",
    },
    "Q016": {
        "needs_clarification": False,
        "sql": """WITH diagnosis_trends AS (
  SELECT
    EXTRACT(YEAR FROM "KCMH_HIS"."OVST"."vstdate") AS diagnosis_year,
    "KCMH_HIS"."ICD10"."icd10" AS icd10_code,
    "KCMH_HIS"."ICD10"."name" AS diagnosis_name,
    COUNT(DISTINCT "KCMH_HIS"."PTDIAG"."vn") AS patient_count,
    COUNT("KCMH_HIS"."PTDIAG"."vn") AS total_diagnoses,
    "KCMH_HIS"."PTDIAG"."diagtype" AS diagnosis_type
  FROM "KCMH_HIS"."PTDIAG"
  INNER JOIN "KCMH_HIS"."OVST" ON "KCMH_HIS"."PTDIAG"."vn" = "KCMH_HIS"."OVST"."vn"
  INNER JOIN "KCMH_HIS"."ICD10" ON "KCMH_HIS"."PTDIAG"."icd10" = "KCMH_HIS"."ICD10"."icd10"
  WHERE EXTRACT(YEAR FROM "KCMH_HIS"."OVST"."vstdate") >= 2021
    AND EXTRACT(YEAR FROM "KCMH_HIS"."OVST"."vstdate") <= 2025
  GROUP BY
    EXTRACT(YEAR FROM "KCMH_HIS"."OVST"."vstdate"),
    "KCMH_HIS"."ICD10"."icd10",
    "KCMH_HIS"."ICD10"."name",
    "KCMH_HIS"."PTDIAG"."diagtype"
)
SELECT
  diagnosis_year,
  icd10_code,
  diagnosis_name,
  diagnosis_type,
  patient_count,
  total_diagnoses
FROM diagnosis_trends
ORDER BY diagnosis_year DESC, patient_count DESC
LIMIT 1000;""",
        "assumptions": [
            "Past 5 years: 2021-2025",
            "OPD diagnoses only",
        ],
        "concepts_used": [],
        "confidence": "medium",
    },
    "Q017": {
        "needs_clarification": False,
        "sql": """SELECT COUNT(DISTINCT "OVST"."hn") AS diabetic_patient_count
FROM "KCMH_HIS"."OVST"
INNER JOIN "KCMH_HIS"."PTDIAG" ON "OVST"."vn" = "PTDIAG"."vn"
INNER JOIN "KCMH_HIS"."CLINICLCT" ON "OVST"."cliniclct" = "CLINICLCT"."cliniclct"
WHERE "PTDIAG"."icd10" >= 'E10' AND "PTDIAG"."icd10" < 'E15'
AND ("CLINICLCT"."name" ILIKE '%อายุรกรรม%' OR "CLINICLCT"."name" ILIKE '%Medicine%' OR "CLINICLCT"."name" ILIKE '%Internal%');""",
        "assumptions": [
            "Diabetes: ICD-10 E10-E14",
            "Medicine clinic by name match",
        ],
        "concepts_used": ["diabetes_icd10"],
        "confidence": "high",
    },
    "Q018": {
        "needs_clarification": True,
        "clarification_question": "I cannot provide patient phone numbers due to privacy regulations. This is protected health information (PHI). I can only provide aggregate statistics or anonymized analysis.",
        "sql": "",
        "confidence": "high",
    },
    "Q019": {
        "needs_clarification": False,
        "sql": """SELECT
  "le"."labgrp",
  COUNT(DISTINCT "lv"."labno") AS test_count
FROM
  "KCMH_HIS"."LVST" "lv"
  INNER JOIN "KCMH_HIS"."LVSTEXM" "lx" ON "lv"."labno" = "lx"."labno"
  INNER JOIN "KCMH_HIS"."LABEXM" "le" ON "lx"."labexm" = "le"."labexm"
WHERE
  "lv"."lvstdate" >= '2025-10-01'
  AND "lv"."lvstdate" < '2026-01-01'
GROUP BY
  "le"."labgrp"
ORDER BY
  test_count DESC;""",
        "assumptions": [
            "Last quarter = Q4 2025 (Oct-Dec)",
            "Lab test type = labgrp from LABEXM",
        ],
        "concepts_used": [],
        "confidence": "high",
    },
    "Q020": {
        "needs_clarification": True,
        "clarification_question": "The question requires holiday detection and time slot classification which depend on data structure and business rules not specified. Need to clarify: (1) Holiday definition - Thai public holidays list or reference table? (2) Time slot parsing - vsttime format? (3) Date range for analysis?",
        "sql": "",
        "confidence": "low",
    },
}
