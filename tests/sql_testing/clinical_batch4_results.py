"""Clinical Complex Batch 4 Results: CQ031-CQ040"""

CLINICAL_BATCH4_RESPONSES = {
    "CQ031": {
        "needs_clarification": False,
        "sql": """WITH leukemia_patients AS (
  SELECT DISTINCT pd.hn
  FROM "KCMH_HIS"."PTDIAG" pd
  WHERE pd.icd10 >= 'C91' AND pd.icd10 <= 'C95'
),
chemo_patients AS (
  SELECT DISTINCT p.hn
  FROM "KCMH_HIS"."PRSC" p
  INNER JOIN "KCMH_HIS"."PRSCDT" pdt ON p.prscno = pdt.prscno
  INNER JOIN "KCMH_HIS"."MEDITEMDIS" m ON pdt.meditem = m.meditem
  WHERE LOWER(m.medname) LIKE '%cytarabine%'
     OR LOWER(m.medname) LIKE '%vincristine%'
     OR LOWER(m.medname) LIKE '%doxorubicin%'
     OR LOWER(m.medname) LIKE '%methotrexate%'
     OR LOWER(m.medname) LIKE '%cyclophosphamide%'
),
neutropenia_patients AS (
  SELECT DISTINCT l.hn
  FROM "KCMH_HIS"."LVSTEXM" l
  INNER JOIN "KCMH_HIS"."LABEXM" le ON l.labexm = le.labexm
  WHERE (LOWER(le.name) LIKE '%neutrophil%' OR LOWER(le.name) LIKE '%anc%')
    AND CAST(l.result AS NUMERIC) < 500
)
SELECT COUNT(DISTINCT lp.hn) AS patient_count
FROM leukemia_patients lp
INNER JOIN chemo_patients cp ON lp.hn = cp.hn
INNER JOIN neutropenia_patients np ON lp.hn = np.hn""",
        "assumptions": ["Leukemia C91-C95", "Chemo agents: cytarabine, vincristine, doxorubicin, methotrexate, cyclophosphamide", "ANC < 500"],
        "confidence": "medium"
    },
    "CQ032": {
        "needs_clarification": True,
        "clarification_question": "Motor fluctuations in Parkinson's disease are clinical symptoms that may not be captured in structured diagnosis codes. Would you like me to: 1) Count Parkinson's patients on levodopa who have been prescribed additional medications (suggesting progression), or 2) Look for specific ICD-10 codes related to drug-induced movement disorders?",
        "sql": "",
        "assumptions": ["Motor fluctuations not reliably captured in structured data"],
        "confidence": "low"
    },
    "CQ033": {
        "needs_clarification": False,
        "sql": """SELECT COUNT(DISTINCT i.an) AS prostatectomy_count
FROM "KCMH_HIS"."IPT" i
INNER JOIN "KCMH_HIS"."IPTSUMOPRT" o ON i.an = o.an
INNER JOIN "KCMH_HIS"."IPTSUMDIAG" d ON i.an = d.an
INNER JOIN "KCMH_HIS"."LVSTEXM" l ON i.hn = l.hn
INNER JOIN "KCMH_HIS"."LABEXM" le ON l.labexm = le.labexm
WHERE o.icd9cm LIKE '60.5%'
AND d.icd10 = 'C61'
AND LOWER(le.name) LIKE '%psa%'
AND CAST(l.result AS NUMERIC) > 20""",
        "assumptions": ["Prostatectomy ICD-9-CM 60.5", "Prostate cancer C61", "PSA > 20"],
        "confidence": "high"
    },
    "CQ034": {
        "needs_clarification": False,
        "sql": """WITH htn_patients AS (
  SELECT DISTINCT pd.hn
  FROM "KCMH_HIS"."PTDIAG" pd
  WHERE pd.icd10 >= 'I10' AND pd.icd10 <= 'I15'
),
multi_drug_patients AS (
  SELECT p.hn, COUNT(DISTINCT m.meditem) AS drug_count
  FROM "KCMH_HIS"."PRSC" p
  INNER JOIN "KCMH_HIS"."PRSCDT" pdt ON p.prscno = pdt.prscno
  INNER JOIN "KCMH_HIS"."MEDITEMDIS" m ON pdt.meditem = m.meditem
  WHERE LOWER(m.medname) LIKE '%amlodipine%'
     OR LOWER(m.medname) LIKE '%losartan%'
     OR LOWER(m.medname) LIKE '%atenolol%'
     OR LOWER(m.medname) LIKE '%hydrochlorothiazide%'
     OR LOWER(m.medname) LIKE '%enalapril%'
     OR LOWER(m.medname) LIKE '%lisinopril%'
     OR LOWER(m.medname) LIKE '%valsartan%'
     OR LOWER(m.medname) LIKE '%metoprolol%'
  GROUP BY p.hn
  HAVING COUNT(DISTINCT m.meditem) >= 3
),
uncontrolled_bp AS (
  SELECT DISTINCT o.hn
  FROM "KCMH_HIS"."OVST" o
  INNER JOIN "KCMH_HIS"."OVSTPRESS" op ON o.vn = op.vn
  WHERE CAST(op.systolic AS NUMERIC) > 140
     OR CAST(op.diastolic AS NUMERIC) > 90
)
SELECT COUNT(DISTINCT hp.hn) AS resistant_htn_count
FROM htn_patients hp
INNER JOIN multi_drug_patients mdp ON hp.hn = mdp.hn
INNER JOIN uncontrolled_bp ubp ON hp.hn = ubp.hn""",
        "assumptions": ["Hypertension I10-I15", "3+ antihypertensives", "BP > 140/90 uncontrolled"],
        "confidence": "medium"
    },
    "CQ035": {
        "needs_clarification": False,
        "sql": """WITH cesarean_sections AS (
  SELECT DISTINCT o.an
  FROM "KCMH_HIS"."IPTSUMOPRT" o
  WHERE o.icd9cm >= '74.0' AND o.icd9cm <= '74.4'
),
with_preeclampsia AS (
  SELECT cs.an, 'With Preeclampsia' AS category
  FROM cesarean_sections cs
  INNER JOIN "KCMH_HIS"."IPTSUMDIAG" d ON cs.an = d.an
  WHERE d.icd10 LIKE 'O14%'
),
without_preeclampsia AS (
  SELECT cs.an, 'Without Preeclampsia' AS category
  FROM cesarean_sections cs
  WHERE cs.an NOT IN (SELECT an FROM with_preeclampsia)
)
SELECT category, COUNT(DISTINCT an) AS count
FROM (
  SELECT * FROM with_preeclampsia
  UNION ALL
  SELECT * FROM without_preeclampsia
) combined
GROUP BY category
ORDER BY category""",
        "assumptions": ["Cesarean section ICD-9-CM 74.0-74.4", "Preeclampsia O14"],
        "confidence": "high"
    },
    "CQ036": {
        "needs_clarification": False,
        "sql": """WITH asthma_patients AS (
  SELECT DISTINCT pd.hn
  FROM "KCMH_HIS"."PTDIAG" pd
  WHERE pd.icd10 LIKE 'J45%'
),
ics_users AS (
  SELECT DISTINCT p.hn
  FROM "KCMH_HIS"."PRSC" p
  INNER JOIN "KCMH_HIS"."PRSCDT" pdt ON p.prscno = pdt.prscno
  INNER JOIN "KCMH_HIS"."MEDITEMDIS" m ON pdt.meditem = m.meditem
  WHERE LOWER(m.medname) LIKE '%budesonide%'
     OR LOWER(m.medname) LIKE '%fluticasone%'
     OR LOWER(m.medname) LIKE '%beclomethasone%'
),
exacerbation_admissions AS (
  SELECT DISTINCT i.hn
  FROM "KCMH_HIS"."IPT" i
  INNER JOIN "KCMH_HIS"."IPTSUMDIAG" d ON i.an = d.an
  WHERE d.icd10 LIKE 'J46%' OR d.icd10 LIKE 'J45%'
)
SELECT COUNT(DISTINCT ap.hn) AS patient_count
FROM asthma_patients ap
INNER JOIN ics_users iu ON ap.hn = iu.hn
INNER JOIN exacerbation_admissions ea ON ap.hn = ea.hn""",
        "assumptions": ["Asthma J45", "ICS: budesonide, fluticasone, beclomethasone", "Exacerbation admission J45/J46"],
        "confidence": "high"
    },
    "CQ037": {
        "needs_clarification": False,
        "sql": """WITH lithium_patients AS (
  SELECT DISTINCT p.hn
  FROM "KCMH_HIS"."PRSC" p
  INNER JOIN "KCMH_HIS"."PRSCDT" pdt ON p.prscno = pdt.prscno
  INNER JOIN "KCMH_HIS"."MEDITEMDIS" m ON pdt.meditem = m.meditem
  WHERE LOWER(m.medname) LIKE '%lithium%'
),
lithium_levels AS (
  SELECT DISTINCT l.hn,
    CAST(l.result AS NUMERIC) AS level_value,
    CASE
      WHEN CAST(l.result AS NUMERIC) BETWEEN 0.6 AND 1.2 THEN 'Therapeutic'
      WHEN CAST(l.result AS NUMERIC) < 0.6 THEN 'Subtherapeutic'
      ELSE 'Supratherapeutic'
    END AS level_category
  FROM "KCMH_HIS"."LVSTEXM" l
  INNER JOIN "KCMH_HIS"."LABEXM" le ON l.labexm = le.labexm
  WHERE LOWER(le.name) LIKE '%lithium%'
)
SELECT COUNT(DISTINCT lp.hn) AS patients_with_monitoring,
       SUM(CASE WHEN ll.level_category = 'Therapeutic' THEN 1 ELSE 0 END) AS therapeutic_count,
       SUM(CASE WHEN ll.level_category = 'Subtherapeutic' THEN 1 ELSE 0 END) AS subtherapeutic_count,
       SUM(CASE WHEN ll.level_category = 'Supratherapeutic' THEN 1 ELSE 0 END) AS supratherapeutic_count
FROM lithium_patients lp
INNER JOIN lithium_levels ll ON lp.hn = ll.hn""",
        "assumptions": ["Lithium prescription", "Lithium level lab", "Therapeutic range 0.6-1.2"],
        "confidence": "high"
    },
    "CQ038": {
        "needs_clarification": False,
        "sql": """SELECT COUNT(DISTINCT i.an) AS angiography_with_cad_count
FROM "KCMH_HIS"."IPT" i
INNER JOIN "KCMH_HIS"."IPTSUMOPRT" o ON i.an = o.an
INNER JOIN "KCMH_HIS"."IPTSUMDIAG" d ON i.an = d.an
WHERE o.icd9cm IN ('88.55', '88.56', '88.57')
AND d.icd10 LIKE 'I25%'""",
        "assumptions": ["Coronary angiography ICD-9-CM 88.55-88.57", "CAD ICD-10 I25", "Same admission"],
        "confidence": "high"
    },
    "CQ039": {
        "needs_clarification": False,
        "sql": """WITH transplant_patients AS (
  SELECT DISTINCT pd.hn
  FROM "KCMH_HIS"."PTDIAG" pd
  WHERE pd.icd10 LIKE 'Z94%'
),
tacrolimus_users AS (
  SELECT DISTINCT p.hn
  FROM "KCMH_HIS"."PRSC" p
  INNER JOIN "KCMH_HIS"."PRSCDT" pdt ON p.prscno = pdt.prscno
  INNER JOIN "KCMH_HIS"."MEDITEMDIS" m ON pdt.meditem = m.meditem
  WHERE LOWER(m.medname) LIKE '%tacrolimus%'
     OR LOWER(m.tradename) LIKE '%prograf%'
),
nephrotoxicity AS (
  SELECT DISTINCT l.hn
  FROM "KCMH_HIS"."LVSTEXM" l
  INNER JOIN "KCMH_HIS"."LABEXM" le ON l.labexm = le.labexm
  WHERE LOWER(le.name) LIKE '%creatinine%'
    AND CAST(l.result AS NUMERIC) > 1.5
)
SELECT COUNT(DISTINCT tp.hn) AS patient_count
FROM transplant_patients tp
INNER JOIN tacrolimus_users tu ON tp.hn = tu.hn
INNER JOIN nephrotoxicity nt ON tp.hn = nt.hn""",
        "assumptions": ["Transplant Z94", "Tacrolimus/Prograf", "Creatinine > 1.5 as nephrotoxicity marker"],
        "confidence": "medium"
    },
    "CQ040": {
        "needs_clarification": False,
        "sql": """WITH copd_patients AS (
  SELECT DISTINCT pd.hn
  FROM "KCMH_HIS"."PTDIAG" pd
  WHERE pd.icd10 LIKE 'J44%'
),
ics_users AS (
  SELECT DISTINCT p.hn
  FROM "KCMH_HIS"."PRSC" p
  INNER JOIN "KCMH_HIS"."PRSCDT" pdt ON p.prscno = pdt.prscno
  INNER JOIN "KCMH_HIS"."MEDITEMDIS" m ON pdt.meditem = m.meditem
  WHERE LOWER(m.medname) LIKE '%fluticasone%'
     OR LOWER(m.medname) LIKE '%budesonide%'
),
laba_users AS (
  SELECT DISTINCT p.hn
  FROM "KCMH_HIS"."PRSC" p
  INNER JOIN "KCMH_HIS"."PRSCDT" pdt ON p.prscno = pdt.prscno
  INNER JOIN "KCMH_HIS"."MEDITEMDIS" m ON pdt.meditem = m.meditem
  WHERE LOWER(m.medname) LIKE '%salmeterol%'
     OR LOWER(m.medname) LIKE '%formoterol%'
),
lama_users AS (
  SELECT DISTINCT p.hn
  FROM "KCMH_HIS"."PRSC" p
  INNER JOIN "KCMH_HIS"."PRSCDT" pdt ON p.prscno = pdt.prscno
  INNER JOIN "KCMH_HIS"."MEDITEMDIS" m ON pdt.meditem = m.meditem
  WHERE LOWER(m.medname) LIKE '%tiotropium%'
     OR LOWER(m.medname) LIKE '%glycopyrronium%'
),
triple_therapy AS (
  SELECT ics.hn
  FROM ics_users ics
  INNER JOIN laba_users laba ON ics.hn = laba.hn
  INNER JOIN lama_users lama ON ics.hn = lama.hn
),
copd_exacerbation AS (
  SELECT DISTINCT i.hn
  FROM "KCMH_HIS"."IPT" i
  INNER JOIN "KCMH_HIS"."IPTSUMDIAG" d ON i.an = d.an
  WHERE d.icd10 LIKE 'J44%'
)
SELECT COUNT(DISTINCT cp.hn) AS patient_count
FROM copd_patients cp
INNER JOIN triple_therapy tt ON cp.hn = tt.hn
INNER JOIN copd_exacerbation ce ON cp.hn = ce.hn""",
        "assumptions": ["COPD J44", "Triple therapy: ICS + LABA + LAMA", "Exacerbation = admission with J44"],
        "confidence": "medium"
    },
}
