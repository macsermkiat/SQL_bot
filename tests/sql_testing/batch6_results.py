"""Batch 6 Results: Q051-Q060"""

BATCH6_RESPONSES = {
    "Q051": {
        "needs_clarification": False,
        "sql": "WITH annual_prescriptions AS (SELECT EXTRACT(YEAR FROM \"KCMH_HIS\".\"PRSC\".\"prscdate\") AS year, \"KCMH_HIS\".\"PRSC\".\"hn\", COUNT(\"KCMH_HIS\".\"PRSC\".\"prscno\") AS prescription_count FROM \"KCMH_HIS\".\"PRSC\" WHERE \"KCMH_HIS\".\"PRSC\".\"prscdate\" IS NOT NULL GROUP BY year, \"KCMH_HIS\".\"PRSC\".\"hn\") SELECT year, COUNT(DISTINCT hn) AS unique_patients, SUM(prescription_count) AS total_prescriptions, ROUND(CAST(SUM(prescription_count) AS DECIMAL) / COUNT(DISTINCT hn), 2) AS avg_prescriptions_per_patient FROM annual_prescriptions GROUP BY year ORDER BY year DESC",
        "assumptions": ["Prescription records grouped by patient and calendar year"],
        "confidence": "high"
    },
    "Q052": {
        "needs_clarification": False,
        "sql": "SELECT COUNT(DISTINCT \"KCMH_HIS\".\"LVSTEXM\".\"hn\") AS patient_count FROM \"KCMH_HIS\".\"LVSTEXM\" JOIN \"KCMH_HIS\".\"LABEXM\" ON \"KCMH_HIS\".\"LVSTEXM\".\"labexm\" = \"KCMH_HIS\".\"LABEXM\".\"labexm\" WHERE \"KCMH_HIS\".\"LABEXM\".\"name\" IN ('AST', 'ALT', 'ALP', 'Total Bilirubin', 'Direct Bilirubin', 'Albumin') AND \"KCMH_HIS\".\"LVSTEXM\".\"result\" IS NOT NULL",
        "assumptions": ["Liver function tests: AST, ALT, ALP, Bilirubin, Albumin"],
        "concepts_used": ["liver_function"],
        "confidence": "medium"
    },
    "Q053": {
        "needs_clarification": True,
        "clarification_question": "Please specify: time period, grouping (monthly vs seasonal), and ER clinic definition.",
        "sql": "",
        "confidence": "low"
    },
    "Q054": {
        "needs_clarification": False,
        "sql": "SELECT pd.icd10, i10.thainame, COUNT(DISTINCT pd.vn) as visit_count, COUNT(DISTINCT pd.hn) as patient_count, ROUND(100.0 * COUNT(DISTINCT pd.hn) / (SELECT COUNT(DISTINCT hn) FROM \"KCMH_HIS\".\"PTDIAG\"), 2) as percentage_of_all_patients FROM \"KCMH_HIS\".\"PTDIAG\" pd LEFT JOIN \"KCMH_HIS\".\"ICD10\" i10 ON pd.icd10 = i10.icd10 WHERE pd.icd10 >= 'I00' AND pd.icd10 < 'J00' GROUP BY pd.icd10, i10.thainame ORDER BY visit_count DESC",
        "assumptions": ["Heart disease ICD-10 range: I00-I99"],
        "confidence": "high"
    },
    "Q055": {
        "needs_clarification": True,
        "clarification_question": "The pttype column is numeric, not text. I cannot filter by the string 'active' on a numeric column.",
        "sql": "",
        "confidence": "high"
    },
    "Q056": {
        "needs_clarification": True,
        "clarification_question": "Please clarify: patients whose registered address is in Bangkok, or patients treated at KCMH?",
        "sql": "",
        "confidence": "medium"
    },
    "Q057": {
        "needs_clarification": True,
        "clarification_question": "I cannot provide individual patient data. This would expose protected health information (PHI).",
        "sql": "",
        "confidence": "high"
    },
    "Q058": {
        "needs_clarification": False,
        "sql": "WITH patient_age_meds AS (SELECT o.vn, o.age, o.ageflag, COUNT(DISTINCT pd.prscno) AS medication_count FROM \"KCMH_HIS\".\"OVST\" o LEFT JOIN \"KCMH_HIS\".\"PRSC\" p ON o.vn = p.vn AND o.hn = p.hn LEFT JOIN \"KCMH_HIS\".\"PRSCDT\" pd ON p.prscno = pd.prscno WHERE o.age IS NOT NULL AND o.ageflag = 'ป' GROUP BY o.vn, o.age, o.ageflag) SELECT age, COUNT(*) AS patient_visit_count, AVG(medication_count) AS avg_medications_per_visit, CORR(age, medication_count) AS age_medication_correlation FROM patient_age_meds GROUP BY age ORDER BY age ASC",
        "assumptions": ["Age measured in years", "Correlation calculated using CORR function"],
        "confidence": "high"
    },
    "Q059": {
        "needs_clarification": False,
        "sql": "SELECT COUNT(DISTINCT \"hn\") AS type2_diabetes_patients FROM \"KCMH_HIS\".\"PTDIAG\" WHERE \"icd10\" LIKE 'E11%'",
        "assumptions": ["Type 2 diabetes identified by ICD-10 code E11%"],
        "concepts_used": ["diabetes_type2"],
        "confidence": "high"
    },
    "Q060": {
        "needs_clarification": True,
        "clarification_question": "I cannot provide data about individual patients as this would expose Protected Health Information (PHI).",
        "sql": "",
        "confidence": "high"
    },
}
