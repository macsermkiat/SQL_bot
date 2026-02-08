"""
Batch 1 Results (Q001-Q010) from Subagent Testing.

Raw responses from parallel subagents for evaluation.
"""

BATCH1_RESPONSES = {
    "Q001": {
        "needs_clarification": False,
        "sql": """WITH diabetes_patients AS (
  SELECT
    DATE_TRUNC('month', "OVST"."vstdate")::DATE AS month_start,
    CASE
      WHEN "PTDIAG"."icd10" LIKE 'E10%' THEN 'Type 1'
      WHEN "PTDIAG"."icd10" LIKE 'E11%' THEN 'Type 2'
    END AS diabetes_type,
    COUNT(DISTINCT "OVST"."hn") AS new_patients
  FROM "KCMH_HIS"."OVST"
  INNER JOIN "KCMH_HIS"."PTDIAG" ON "OVST"."vn" = "PTDIAG"."vn"
  WHERE "OVST"."vstdate" >= '2024-01-01'
    AND "OVST"."vstdate" < '2026-02-07'
    AND ("PTDIAG"."icd10" LIKE 'E10%' OR "PTDIAG"."icd10" LIKE 'E11%')
    AND "PTDIAG"."diagtype" = '1'
  GROUP BY DATE_TRUNC('month', "OVST"."vstdate"), diabetes_type
),
monthly_trend AS (
  SELECT
    month_start,
    diabetes_type,
    new_patients,
    LAG(new_patients) OVER (PARTITION BY diabetes_type ORDER BY month_start) AS prev_month_patients,
    CASE
      WHEN LAG(new_patients) OVER (PARTITION BY diabetes_type ORDER BY month_start) = 0 THEN NULL
      WHEN LAG(new_patients) OVER (PARTITION BY diabetes_type ORDER BY month_start) IS NULL THEN NULL
      ELSE ROUND(
        ((new_patients - LAG(new_patients) OVER (PARTITION BY diabetes_type ORDER BY month_start))::NUMERIC /
         LAG(new_patients) OVER (PARTITION BY diabetes_type ORDER BY month_start)) * 100,
        2
      )
    END AS mom_growth_rate_pct
  FROM diabetes_patients
)
SELECT
  month_start,
  diabetes_type,
  new_patients,
  mom_growth_rate_pct
FROM monthly_trend
ORDER BY month_start, diabetes_type;""",
        "assumptions": [
            "New diabetes patients defined as first occurrence of diabetes diagnosis (E10% or E11%) in OPD visit",
            "diagtype = '1' indicates primary diagnosis",
            "Month-over-month growth rate calculated from same diabetes type across consecutive months",
        ],
        "concepts_used": ["diabetes_type1", "diabetes_type2"],
        "confidence": "medium",
    },
    "Q002": {
        "needs_clarification": False,
        "sql": """WITH opd_2025 AS (
  SELECT
    "KCMH_HIS"."CLINICLCT"."clinictype",
    COUNT(DISTINCT "KCMH_HIS"."OVST"."vn") as visit_count_2025
  FROM "KCMH_HIS"."OVST"
  INNER JOIN "KCMH_HIS"."CLINICLCT"
    ON "KCMH_HIS"."OVST"."cliniclct" = "KCMH_HIS"."CLINICLCT"."cliniclct"
  WHERE EXTRACT(YEAR FROM "KCMH_HIS"."OVST"."vstdate") = 2025
  GROUP BY "KCMH_HIS"."CLINICLCT"."clinictype"
),
opd_2026 AS (
  SELECT
    "KCMH_HIS"."CLINICLCT"."clinictype",
    COUNT(DISTINCT "KCMH_HIS"."OVST"."vn") as visit_count_2026
  FROM "KCMH_HIS"."OVST"
  INNER JOIN "KCMH_HIS"."CLINICLCT"
    ON "KCMH_HIS"."OVST"."cliniclct" = "KCMH_HIS"."CLINICLCT"."cliniclct"
  WHERE EXTRACT(YEAR FROM "KCMH_HIS"."OVST"."vstdate") = 2026
  GROUP BY "KCMH_HIS"."CLINICLCT"."clinictype"
)
SELECT
  COALESCE(opd_2025.clinictype, opd_2026.clinictype) as clinic_category,
  COALESCE(opd_2025.visit_count_2025, 0) as visits_2025,
  COALESCE(opd_2026.visit_count_2026, 0) as visits_2026,
  COALESCE(opd_2026.visit_count_2026, 0) - COALESCE(opd_2025.visit_count_2025, 0) as absolute_change,
  CASE
    WHEN COALESCE(opd_2025.visit_count_2025, 0) = 0 THEN NULL
    ELSE ROUND(
      ((COALESCE(opd_2026.visit_count_2026, 0) - COALESCE(opd_2025.visit_count_2025, 0))::numeric / COALESCE(opd_2025.visit_count_2025, 0)) * 100,
      2
    )
  END as yoy_growth_percent
FROM opd_2025
FULL OUTER JOIN opd_2026
  ON opd_2025.clinictype = opd_2026.clinictype
WHERE
  ABS(COALESCE(opd_2026.visit_count_2026, 0) - COALESCE(opd_2025.visit_count_2025, 0)) > 0
  AND (
    CASE
      WHEN COALESCE(opd_2025.visit_count_2025, 0) = 0 THEN TRUE
      ELSE ABS(
        ((COALESCE(opd_2026.visit_count_2026, 0) - COALESCE(opd_2025.visit_count_2025, 0))::numeric / COALESCE(opd_2025.visit_count_2025, 0)) * 100
      ) >= 20
      OR COALESCE(opd_2026.visit_count_2026, 0) < COALESCE(opd_2025.visit_count_2025, 0)
    END
  )
ORDER BY absolute_change DESC;""",
        "assumptions": [
            "OPD visits identified by OVST table records",
            "Clinic category is derived from CLINICLCT.clinictype",
        ],
        "concepts_used": ["opd_visit"],
        "confidence": "high",
    },
    "Q003": {
        "needs_clarification": True,
        "clarification_question": "I cannot provide patient-level identifiable information (names, HN, etc.) due to privacy regulations. Instead, I can provide: (1) Total count of patients with diabetes, (2) Diabetes prevalence by age group or department, (3) Diabetes cases by visit type (OPD/IPD), or (4) Trend of diabetes diagnoses over time. Which would be most helpful?",
        "sql": "",
        "confidence": "high",
    },
    "Q004": {
        "needs_clarification": False,
        "sql": """SELECT COUNT(DISTINCT "KCMH_HIS"."PTDIAG"."hn") AS patient_count FROM "KCMH_HIS"."PTDIAG" WHERE ("KCMH_HIS"."PTDIAG"."icd10" >= 'E10' AND "KCMH_HIS"."PTDIAG"."icd10" < 'E15') AND "KCMH_HIS"."PTDIAG"."hn" IN (SELECT DISTINCT "KCMH_HIS"."PTDIAG"."hn" FROM "KCMH_HIS"."PTDIAG" WHERE "KCMH_HIS"."PTDIAG"."icd10" >= 'I10' AND "KCMH_HIS"."PTDIAG"."icd10" < 'I16')""",
        "assumptions": [
            "Patients with both conditions identified by having at least one diagnosis record with diabetes ICD-10 and at least one with hypertension",
            "Using PTDIAG table which contains OPD diagnoses",
        ],
        "concepts_used": ["diabetes_icd10", "hypertension"],
        "confidence": "high",
    },
    "Q005": {
        "needs_clarification": False,
        "sql": """WITH thyroid_lab_orders AS (
  SELECT DISTINCT l."labno"
  FROM "KCMH_HIS"."LVST" l
  INNER JOIN "KCMH_HIS"."LVSTEXM" le ON l."labno" = le."labno"
  INNER JOIN "KCMH_HIS"."LABEXM" lab ON le."labexm" = lab."labexm"
  WHERE EXTRACT(YEAR FROM l."lvstdate") = 2025
    AND (
      lab."name" ILIKE '%FT3%'
      OR lab."name" ILIKE '%TSH%'
      OR lab."name" ILIKE '%FT4%'
    )
  GROUP BY l."labno"
  HAVING COUNT(DISTINCT CASE
    WHEN lab."name" ILIKE '%FT3%' THEN 'FT3'
    WHEN lab."name" ILIKE '%TSH%' THEN 'TSH'
    WHEN lab."name" ILIKE '%FT4%' THEN 'FT4'
  END) = 3
)
SELECT
  COUNT(DISTINCT to."labno") AS thyroid_bundle_orders,
  COUNT(DISTINCT al."labno") AS total_lab_orders,
  ROUND(
    (COUNT(DISTINCT CASE WHEN tlo."labno" IS NOT NULL THEN to."labno" END)::NUMERIC /
     COUNT(DISTINCT al."labno")::NUMERIC) * 100,
    2
  ) AS percentage_thyroid_bundles
FROM "KCMH_HIS"."LVST" al
LEFT JOIN thyroid_lab_orders tlo ON al."labno" = tlo."labno"
WHERE EXTRACT(YEAR FROM al."lvstdate") = 2025""",
        "assumptions": [
            "Last year is 2025",
            "Thyroid function test bundle defined as: FT3, FT4, TSH all in same lab order (same labno)",
        ],
        "concepts_used": ["thyroid_function_test"],
        "confidence": "medium",
    },
    "Q006": {
        "needs_clarification": True,
        "clarification_question": "I cannot perform DELETE operations. This is a read-only analytics chatbot designed for data analysis only. All write operations (DELETE, UPDATE, INSERT, DROP, etc.) are forbidden by design to protect patient data and database integrity.",
        "sql": "",
        "confidence": "high",
    },
    "Q007": {
        "needs_clarification": False,
        "sql": """WITH last_month_prescriptions AS (
  SELECT
    p."prscno",
    o."cliniclct"
  FROM "KCMH_HIS"."PRSC" p
  INNER JOIN "KCMH_HIS"."OVST" o ON p."vn" = o."vn"
  WHERE p."prscdate" >= '2026-01-01'
    AND p."prscdate" < '2026-02-01'
)
SELECT
  c."cliniclct",
  c."name" AS clinic_name,
  COUNT(lmp."prscno") AS prescription_count
FROM last_month_prescriptions lmp
INNER JOIN "KCMH_HIS"."CLINICLCT" c ON lmp."cliniclct" = c."cliniclct"
GROUP BY c."cliniclct", c."name"
ORDER BY prescription_count DESC;""",
        "assumptions": [
            "Last month refers to January 2026",
            "Prescriptions are linked to clinics through OVST via vn",
        ],
        "concepts_used": [],
        "confidence": "high",
    },
    "Q008": {
        "needs_clarification": True,
        "clarification_question": "I cannot provide patient HN (Hospital Number) or any patient-identifying information due to privacy regulations. This would violate patient confidentiality and data protection requirements. Instead, I can provide aggregate statistics such as: (1) Count of patients with high blood pressure, (2) Breakdown by age group or gender, (3) Percentage of patients with hypertension, or (4) Trends over time. Which would be most helpful?",
        "sql": "",
        "confidence": "high",
    },
    "Q009": {
        "needs_clarification": False,
        "sql": """WITH ipd_admissions AS (
  SELECT
    "an",
    "admdate",
    "dchdate",
    "ward",
    EXTRACT(YEAR FROM "admdate")::INTEGER AS admit_year,
    ("dchdate" - "admdate")::INTEGER AS los_days
  FROM "KCMH_HIS"."IPT"
  WHERE "dchdate" IS NOT NULL
    AND "admdate" IS NOT NULL
    AND EXTRACT(YEAR FROM "admdate") IN (2025, 2026)
),
icd_chapters AS (
  SELECT
    "an",
    SUBSTRING("icd10", 1, 1) AS icd10_chapter
  FROM "KCMH_HIS"."IPTSUMDIAG"
  WHERE "diagtype" = 1
),
ward_admissions AS (
  SELECT
    "admit_year",
    "icd10_chapter",
    "ward",
    COUNT(DISTINCT "an") AS admission_count,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY "los_days") AS p25_los,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY "los_days") AS p50_los,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY "los_days") AS p75_los,
    PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY "los_days") AS p90_los
  FROM ipd_admissions
  JOIN icd_chapters USING ("an")
  GROUP BY "admit_year", "icd10_chapter", "ward"
  HAVING COUNT(DISTINCT "an") >= 50
)
SELECT
  "admit_year" AS year,
  "icd10_chapter",
  "ward",
  "admission_count",
  ROUND("p25_los"::NUMERIC, 2) AS p25_percentile_los,
  ROUND("p50_los"::NUMERIC, 2) AS p50_percentile_los,
  ROUND("p75_los"::NUMERIC, 2) AS p75_percentile_los,
  ROUND("p90_los"::NUMERIC, 2) AS p90_percentile_los
FROM ward_admissions
ORDER BY "admit_year" DESC, "icd10_chapter", "ward";""",
        "assumptions": [
            "Primary diagnosis identified by diagtype = 1",
            "ICD-10 chapter derived from first character of icd10 code",
            "Length of stay calculated as dchdate - admdate in days",
        ],
        "concepts_used": ["ipd_admission"],
        "confidence": "high",
    },
    "Q010": {
        "needs_clarification": False,
        # Note: This SQL has syntax errors (TOP 10 is SQL Server, YEAR() instead of EXTRACT)
        "sql": """SELECT TOP 10 m.meditemdis, m.medname, m.tradename, COUNT(*) AS prescription_count, SUM(pd.qty) AS total_qty FROM "KCMH_HIS"."PRSCDT" pd JOIN "KCMH_HIS"."PRSC" p ON pd.prscno = p.prscno JOIN "KCMH_HIS"."MEDITEMDIS" m ON pd.meditemdis = m.meditemdis WHERE YEAR(p.prscdate) = 2026 GROUP BY m.meditemdis, m.medname, m.tradename ORDER BY prescription_count DESC;""",
        "assumptions": [
            "Year 2026 means prescriptions with prscdate in calendar year 2026",
            "Top 10 by prescription count",
        ],
        "concepts_used": [],
        "confidence": "high",
    },
}
