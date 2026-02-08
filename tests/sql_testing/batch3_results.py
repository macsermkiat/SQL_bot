"""Batch 3 Results: Q021-Q030"""

BATCH3_RESPONSES = {
    "Q021": {
        "needs_clarification": False,
        "sql": "SELECT \"DCT\".\"dct\", \"DCT\".\"fname\", \"DCT\".\"lname\", \"DCT\".\"spclty\", COUNT(\"OVST\".\"vn\") AS visit_count FROM \"KCMH_HIS\".\"OVST\" JOIN \"KCMH_HIS\".\"DCT\" ON \"OVST\".\"dct\" = \"DCT\".\"dct\" GROUP BY \"DCT\".\"dct\", \"DCT\".\"fname\", \"DCT\".\"lname\", \"DCT\".\"spclty\" ORDER BY visit_count DESC LIMIT 100",
        "assumptions": ["Doctors are identified in OVST.dct column", "Patient visits are OPD visits"],
        "confidence": "high"
    },
    "Q022": {
        "needs_clarification": True,
        "clarification_question": "I cannot provide patient-level identifiable information (names, HN, addresses, phone numbers, etc.) due to privacy regulations.",
        "sql": "",
        "confidence": "high"
    },
    "Q023": {
        "needs_clarification": True,
        "clarification_question": "Please specify the time period for comparison and whether you want admission counts or rates.",
        "sql": "",
        "confidence": "low"
    },
    "Q024": {
        "needs_clarification": False,
        "sql": "WITH diagnosis_pairs AS (SELECT p1.\"icd10\" AS diagnosis1, p2.\"icd10\" AS diagnosis2, COUNT(DISTINCT p1.\"vn\") AS joint_frequency FROM \"KCMH_HIS\".\"PTDIAG\" p1 INNER JOIN \"KCMH_HIS\".\"PTDIAG\" p2 ON p1.\"vn\" = p2.\"vn\" AND p1.\"icd10\" < p2.\"icd10\" GROUP BY p1.\"icd10\", p2.\"icd10\"), diagnosis_counts AS (SELECT \"icd10\", COUNT(DISTINCT \"vn\") AS visit_count FROM \"KCMH_HIS\".\"PTDIAG\" GROUP BY \"icd10\"), ranked_pairs AS (SELECT dp.diagnosis1, dp.diagnosis2, dp.joint_frequency, dc1.visit_count AS freq_diagnosis1, dc2.visit_count AS freq_diagnosis2, ROUND(CAST(dp.joint_frequency AS NUMERIC) / (CAST(dc1.visit_count AS NUMERIC) * CAST(dc2.visit_count AS NUMERIC)) * (SELECT COUNT(DISTINCT \"vn\") FROM \"KCMH_HIS\".\"PTDIAG\"), 4) AS lift_ratio, ROW_NUMBER() OVER (ORDER BY dp.joint_frequency DESC) AS rank FROM diagnosis_pairs dp INNER JOIN diagnosis_counts dc1 ON dp.diagnosis1 = dc1.\"icd10\" INNER JOIN diagnosis_counts dc2 ON dp.diagnosis2 = dc2.\"icd10\") SELECT diagnosis1, diagnosis2, joint_frequency, freq_diagnosis1, freq_diagnosis2, lift_ratio FROM ranked_pairs WHERE rank <= 10 ORDER BY rank",
        "assumptions": ["Using PTDIAG table for OPD diagnoses"],
        "confidence": "high"
    },
    "Q025": {
        "needs_clarification": True,
        "clarification_question": "The prscst (prescription status) column is numeric, not text. I cannot use LIKE 'A%' on numeric columns.",
        "sql": "",
        "confidence": "high"
    },
    "Q026": {
        "needs_clarification": False,
        "sql": "WITH diabetes_visits AS (SELECT DISTINCT \"OVST\".\"vn\", EXTRACT(YEAR FROM \"OVST\".\"vstdate\") AS visit_year, EXTRACT(MONTH FROM \"OVST\".\"vstdate\") AS visit_month FROM \"KCMH_HIS\".\"OVST\" INNER JOIN \"KCMH_HIS\".\"PTDIAG\" ON \"OVST\".\"vn\" = \"PTDIAG\".\"vn\" WHERE \"PTDIAG\".\"icd10\" >= 'E10' AND \"PTDIAG\".\"icd10\" < 'E15'), monthly_trend AS (SELECT visit_year, visit_month, COUNT(DISTINCT \"vn\") AS new_diagnoses_count FROM diabetes_visits GROUP BY visit_year, visit_month) SELECT visit_year AS year, visit_month AS month, new_diagnoses_count FROM monthly_trend ORDER BY visit_year, visit_month",
        "assumptions": ["Diabetes defined as ICD-10 codes E10-E14"],
        "concepts_used": ["diabetes_icd10"],
        "confidence": "high"
    },
    "Q027": {
        "needs_clarification": True,
        "clarification_question": "I cannot perform DROP operations. This is a read-only system that only supports SELECT queries.",
        "sql": "",
        "confidence": "high"
    },
    "Q028": {
        "needs_clarification": False,
        "sql": "SELECT \"PTTYPE\".\"pttype\", \"PTTYPE\".\"name\", COUNT(DISTINCT \"OVST\".\"hn\") as patient_count FROM \"KCMH_HIS\".\"OVST\" \"OVST\" JOIN \"KCMH_HIS\".\"PTTYPE\" \"PTTYPE\" ON \"OVST\".\"pttype\" = \"PTTYPE\".\"pttype\" GROUP BY \"PTTYPE\".\"pttype\", \"PTTYPE\".\"name\" ORDER BY patient_count DESC LIMIT 100",
        "assumptions": ["Using PTTYPE field to identify insurance/patient types"],
        "confidence": "medium"
    },
    "Q029": {
        "needs_clarification": True,
        "clarification_question": "The OVST table contains vstdate and vsttime but lacks explicit check-in time or consultation start time columns needed to calculate wait time.",
        "sql": "",
        "confidence": "high"
    },
    "Q030": {
        "needs_clarification": False,
        "sql": "SELECT COUNT(DISTINCT \"LVST\".\"hn\") AS patient_count FROM \"KCMH_HIS\".\"LVST\" cbc_visit JOIN \"KCMH_HIS\".\"LVST\" lipid_visit ON cbc_visit.\"hn\" = lipid_visit.\"hn\" AND DATE(cbc_visit.\"lvstdate\") = DATE(lipid_visit.\"lvstdate\") JOIN \"KCMH_HIS\".\"LVSTEXM\" cbc_result ON cbc_visit.\"labno\" = cbc_result.\"labno\" JOIN \"KCMH_HIS\".\"LVSTEXM\" lipid_result ON lipid_visit.\"labno\" = lipid_result.\"labno\" JOIN \"KCMH_HIS\".\"LABEXM\" cbc_exam ON cbc_result.\"labexm\" = cbc_exam.\"labexm\" JOIN \"KCMH_HIS\".\"LABEXM\" lipid_exam ON lipid_result.\"labexm\" = lipid_exam.\"labexm\" WHERE (LOWER(cbc_exam.\"name\") LIKE '%cbc%' OR LOWER(cbc_exam.\"name\") LIKE '%hemoglobin%' OR LOWER(cbc_exam.\"name\") LIKE '%wbc%' OR LOWER(cbc_exam.\"name\") LIKE '%platelet%') AND (LOWER(lipid_exam.\"name\") LIKE '%cholesterol%' OR LOWER(lipid_exam.\"name\") LIKE '%triglyceride%' OR LOWER(lipid_exam.\"name\") LIKE '%hdl%' OR LOWER(lipid_exam.\"name\") LIKE '%ldl%')",
        "assumptions": ["CBC components identified by name matching", "Same day determined by DATE equality"],
        "concepts_used": ["complete_blood_count", "lipid_profile"],
        "confidence": "medium"
    },
}
