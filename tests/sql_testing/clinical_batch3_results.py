"""Clinical Complex Batch 3 Results: CQ021-CQ030"""

CLINICAL_BATCH3_RESPONSES = {
    "CQ021": {
        "needs_clarification": False,
        "sql": """WITH cirrhosis_patients AS (
  SELECT DISTINCT pd.hn
  FROM "KCMH_HIS"."PTDIAG" pd
  WHERE pd.icd10 LIKE 'K74%'
),
spironolactone_users AS (
  SELECT DISTINCT p.hn
  FROM "KCMH_HIS"."PRSC" p
  INNER JOIN "KCMH_HIS"."PRSCDT" pd ON p.prscno = pd.prscno
  INNER JOIN "KCMH_HIS"."MEDITEMDIS" m ON pd.meditem = m.meditem
  WHERE (LOWER(m.medname) LIKE '%spironolactone%'
     OR LOWER(m.tradename) LIKE '%aldactone%')
),
hyponatremia_cases AS (
  SELECT DISTINCT l.hn
  FROM "KCMH_HIS"."LVSTEXM" l
  INNER JOIN "KCMH_HIS"."LABEXM" le ON l.labexm = le.labexm
  WHERE LOWER(le.name) LIKE '%sodium%'
    AND CAST(l.result AS NUMERIC) < 130
)
SELECT COUNT(DISTINCT cp.hn) AS patient_count
FROM cirrhosis_patients cp
INNER JOIN spironolactone_users su ON cp.hn = su.hn
INNER JOIN hyponatremia_cases hc ON cp.hn = hc.hn""",
        "assumptions": ["Liver cirrhosis K74", "Spironolactone/Aldactone", "Sodium < 130"],
        "confidence": "high"
    },
    "CQ022": {
        "needs_clarification": False,
        "sql": """WITH knee_replacement AS (
  SELECT DISTINCT op.an, ipt.hn
  FROM "KCMH_HIS"."IPTSUMOPRT" op
  INNER JOIN "KCMH_HIS"."IPT" ipt ON op.an = ipt.an
  WHERE op.icd9cm = '81.54'
),
osteoarthritis AS (
  SELECT DISTINCT an
  FROM "KCMH_HIS"."IPTSUMDIAG"
  WHERE icd10 LIKE 'M17%'
),
obesity AS (
  SELECT DISTINCT an
  FROM "KCMH_HIS"."IPTSUMDIAG"
  WHERE icd10 LIKE 'E66%'
)
SELECT COUNT(DISTINCT kr.an) AS admission_count
FROM knee_replacement kr
INNER JOIN osteoarthritis oa ON kr.an = oa.an
INNER JOIN obesity ob ON kr.an = ob.an""",
        "assumptions": ["Knee replacement ICD-9-CM 81.54", "Osteoarthritis M17", "Obesity E66", "Same admission"],
        "confidence": "high"
    },
    "CQ023": {
        "needs_clarification": False,
        "sql": """WITH stroke_patients AS (
  SELECT DISTINCT pd.hn
  FROM "KCMH_HIS"."PTDIAG" pd
  WHERE pd.icd10 >= 'I60' AND pd.icd10 < 'I70'
),
hem_patients AS (
  SELECT DISTINCT pd.hn
  FROM "KCMH_HIS"."PTDIAG" pd
  WHERE pd.icd10 >= 'I60' AND pd.icd10 < 'I63'
),
anticoagulant_patients AS (
  SELECT DISTINCT pr.hn
  FROM "KCMH_HIS"."PRSC" pr
  INNER JOIN "KCMH_HIS"."PRSCDT" pdt ON pr.prscno = pdt.prscno
  INNER JOIN "KCMH_HIS"."MEDITEMDIS" mid ON pdt.meditem = mid.meditem
  WHERE LOWER(mid.medname) LIKE '%warfarin%'
    OR LOWER(mid.medname) LIKE '%rivaroxaban%'
    OR LOWER(mid.medname) LIKE '%dabigatran%'
    OR LOWER(mid.medname) LIKE '%apixaban%'
)
SELECT COUNT(DISTINCT s.hn) AS patient_count
FROM stroke_patients s
INNER JOIN hem_patients h ON s.hn = h.hn
INNER JOIN anticoagulant_patients a ON s.hn = a.hn""",
        "assumptions": ["Stroke I60-I69", "Intracranial hemorrhage I60-I62", "Anticoagulants: warfarin, rivaroxaban, dabigatran, apixaban"],
        "confidence": "medium"
    },
    "CQ024": {
        "needs_clarification": False,
        "sql": """WITH thyroidectomy_procedures AS (
  SELECT DISTINCT op.an
  FROM "KCMH_HIS"."IPTSUMOPRT" op
  WHERE op.icd9cm >= '06.2' AND op.icd9cm <= '06.5'
),
thyroidectomy_diagnoses AS (
  SELECT
    te.an,
    CASE
      WHEN diag.icd10 = 'C73' THEN 'Cancer'
      WHEN diag.icd10 LIKE 'E04%' OR diag.icd10 LIKE 'E01%' THEN 'Benign'
      ELSE 'Other'
    END AS primary_category
  FROM thyroidectomy_procedures te
  INNER JOIN "KCMH_HIS"."IPTSUMDIAG" diag ON te.an = diag.an
)
SELECT
  primary_category,
  COUNT(DISTINCT an) AS number_of_admissions
FROM thyroidectomy_diagnoses
WHERE primary_category IN ('Cancer', 'Benign')
GROUP BY primary_category
ORDER BY primary_category""",
        "assumptions": ["Thyroidectomy ICD-9-CM 06.2-06.5", "Thyroid cancer C73", "Benign: E04, E01"],
        "confidence": "medium"
    },
    "CQ025": {
        "needs_clarification": False,
        "sql": """SELECT COUNT(DISTINCT pd.hn) AS patient_count
FROM "KCMH_HIS"."PTDIAG" pd
INNER JOIN "KCMH_HIS"."PRSC" prsc ON pd.hn = prsc.hn
INNER JOIN "KCMH_HIS"."PRSCDT" prscdt ON prsc.prscno = prscdt.prscno
INNER JOIN "KCMH_HIS"."MEDITEMDIS" med ON prscdt.meditem = med.meditem
INNER JOIN "KCMH_HIS"."LVSTEXM" lv ON pd.hn = lv.hn
INNER JOIN "KCMH_HIS"."LABEXM" le ON lv.labexm = le.labexm
WHERE pd.icd10 >= 'B20' AND pd.icd10 <= 'B24'
AND (LOWER(med.medname) LIKE '%efavirenz%'
     OR LOWER(med.medname) LIKE '%tenofovir%'
     OR LOWER(med.medname) LIKE '%lamivudine%'
     OR LOWER(med.medname) LIKE '%lopinavir%')
AND (LOWER(le.name) LIKE '%viral load%' OR LOWER(le.name) LIKE '%hiv rna%')
AND CAST(lv.result AS NUMERIC) > 50""",
        "assumptions": ["HIV B20-B24", "ARV drugs: efavirenz, tenofovir, lamivudine, lopinavir", "Viral load > 50"],
        "confidence": "medium"
    },
    "CQ026": {
        "needs_clarification": False,
        "sql": """WITH anemia_patients AS (
  SELECT DISTINCT ptdiag.hn
  FROM "KCMH_HIS"."PTDIAG" ptdiag
  WHERE ptdiag.icd10 >= 'D50' AND ptdiag.icd10 <= 'D64'
),
epo_prescriptions AS (
  SELECT DISTINCT prsc.hn
  FROM "KCMH_HIS"."PRSC" prsc
  INNER JOIN "KCMH_HIS"."PRSCDT" prscdt ON prsc.prscno = prscdt.prscno
  INNER JOIN "KCMH_HIS"."MEDITEMDIS" med ON prscdt.meditem = med.meditem
  WHERE LOWER(med.medname) LIKE '%erythropoietin%'
    OR LOWER(med.medname) LIKE '%epoetin%'
    OR LOWER(med.medname) LIKE '%darbepoetin%'
),
hemoglobin_results AS (
  SELECT DISTINCT lexm.hn
  FROM "KCMH_HIS"."LVSTEXM" lexm
  INNER JOIN "KCMH_HIS"."LABEXM" labexm ON lexm.labexm = labexm.labexm
  WHERE (LOWER(labexm.name) LIKE '%hemoglobin%' OR LOWER(labexm.name) LIKE '%hb%')
  AND CAST(lexm.result AS NUMERIC) > 10
)
SELECT COUNT(DISTINCT ap.hn) AS anemia_patients_on_epo_with_hb_gt_10
FROM anemia_patients ap
INNER JOIN epo_prescriptions ep ON ap.hn = ep.hn
INNER JOIN hemoglobin_results hr ON ap.hn = hr.hn""",
        "assumptions": ["Anemia D50-D64", "EPO/Epoetin/Darbepoetin", "Hemoglobin > 10"],
        "confidence": "high"
    },
    "CQ027": {
        "needs_clarification": False,
        "sql": """SELECT COUNT(DISTINCT gout_patients.hn) AS gout_patients_on_allopurinol_with_target_uric_acid
FROM (
  SELECT DISTINCT pt_diag.hn
  FROM "KCMH_HIS"."PTDIAG" pt_diag
  WHERE pt_diag.icd10 LIKE 'M10%'
) AS gout_patients
INNER JOIN (
  SELECT DISTINCT prsc.hn
  FROM "KCMH_HIS"."PRSC" prsc
  INNER JOIN "KCMH_HIS"."PRSCDT" prscdt ON prsc.prscno = prscdt.prscno
  INNER JOIN "KCMH_HIS"."MEDITEMDIS" med ON prscdt.meditem = med.meditem
  WHERE LOWER(med.medname) LIKE '%allopurinol%'
) AS allopurinol_patients ON gout_patients.hn = allopurinol_patients.hn
INNER JOIN (
  SELECT DISTINCT hn
  FROM "KCMH_HIS"."LVSTEXM" lexm
  INNER JOIN "KCMH_HIS"."LABEXM" lab ON lexm.labexm = lab.labexm
  WHERE LOWER(lab.name) LIKE '%uric acid%'
  AND CAST(lexm.result AS NUMERIC) < 6
) AS target_uric_acid ON gout_patients.hn = target_uric_acid.hn""",
        "assumptions": ["Gout M10", "Allopurinol", "Uric acid < 6"],
        "confidence": "medium"
    },
    "CQ028": {
        "needs_clarification": False,
        "sql": """WITH af_patients AS (
  SELECT DISTINCT pd.hn
  FROM "KCMH_HIS"."PTDIAG" pd
  WHERE pd.icd10 LIKE 'I48%'
),
digoxin_rx AS (
  SELECT DISTINCT p.hn
  FROM "KCMH_HIS"."PRSC" p
  INNER JOIN "KCMH_HIS"."PRSCDT" pd ON p.prscno = pd.prscno
  INNER JOIN "KCMH_HIS"."MEDITEMDIS" m ON pd.meditem = m.meditem
  WHERE (LOWER(m.medname) LIKE '%digoxin%' OR LOWER(m.tradename) LIKE '%lanoxin%')
),
low_potassium AS (
  SELECT DISTINCT l.hn
  FROM "KCMH_HIS"."LVSTEXM" l
  INNER JOIN "KCMH_HIS"."LABEXM" le ON l.labexm = le.labexm
  WHERE LOWER(le.name) LIKE '%potassium%'
    AND CAST(l.result AS NUMERIC) < 3.5
)
SELECT COUNT(DISTINCT af.hn) AS patient_count
FROM af_patients af
INNER JOIN digoxin_rx drx ON af.hn = drx.hn
INNER JOIN low_potassium lk ON af.hn = lk.hn""",
        "assumptions": ["Atrial fibrillation I48", "Digoxin/Lanoxin", "Potassium < 3.5", "Bradycardia excluded due to limited vitals data"],
        "confidence": "medium"
    },
    "CQ029": {
        "needs_clarification": False,
        "sql": """SELECT COUNT(DISTINCT i.an) AS colectomy_count
FROM "KCMH_HIS"."IPT" i
INNER JOIN "KCMH_HIS"."IPTSUMOPRT" o ON i.an = o.an
INNER JOIN "KCMH_HIS"."IPTSUMDIAG" d1 ON i.an = d1.an
INNER JOIN "KCMH_HIS"."IPTSUMDIAG" d2 ON i.an = d2.an
WHERE o.icd9cm >= '45.7' AND o.icd9cm <= '45.8'
AND (d1.icd10 LIKE 'C18%' OR d1.icd10 LIKE 'C19%' OR d1.icd10 LIKE 'C20%')
AND d2.icd10 LIKE 'C77%'""",
        "assumptions": ["Colectomy ICD-9-CM 45.7-45.8", "Colorectal cancer C18-C20", "Lymph node involvement C77"],
        "confidence": "medium"
    },
    "CQ030": {
        "needs_clarification": False,
        "sql": """WITH ra_patients AS (
  SELECT DISTINCT d1.hn
  FROM "KCMH_HIS"."PTDIAG" d1
  WHERE d1.icd10 LIKE 'M05%' OR d1.icd10 LIKE 'M06%'
),
biologic_users AS (
  SELECT DISTINCT p.hn
  FROM "KCMH_HIS"."PRSC" p
  INNER JOIN "KCMH_HIS"."PRSCDT" pd ON p.prscno = pd.prscno
  INNER JOIN "KCMH_HIS"."MEDITEMDIS" m ON pd.meditem = m.meditem
  WHERE LOWER(m.medname) LIKE '%adalimumab%'
     OR LOWER(m.medname) LIKE '%etanercept%'
     OR LOWER(m.medname) LIKE '%infliximab%'
     OR LOWER(m.medname) LIKE '%tocilizumab%'
),
infection_patients AS (
  SELECT DISTINCT d2.hn
  FROM "KCMH_HIS"."PTDIAG" d2
  WHERE d2.icd10 >= 'A00' AND d2.icd10 < 'C00'
)
SELECT COUNT(DISTINCT ra.hn) AS ra_patients_on_biologics_with_infections
FROM ra_patients ra
INNER JOIN biologic_users bu ON ra.hn = bu.hn
INNER JOIN infection_patients inf ON ra.hn = inf.hn""",
        "assumptions": ["RA M05-M06", "Biologics: adalimumab, etanercept, infliximab, tocilizumab", "Infections A00-B99"],
        "confidence": "medium"
    },
}
