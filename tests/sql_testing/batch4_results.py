"""Batch 4 Results: Q031-Q040"""

BATCH4_RESPONSES = {
    "Q031": {
        "needs_clarification": True,
        "clarification_question": "ไม่สามารถให้ข้อมูลส่วนตัวของผู้ป่วย (ชื่อ, HN, เบอร์โทร, ที่อยู่) ได้เนื่องจากกฎหมายคุ้มครองข้อมูลส่วนบุคคล",
        "sql": "",
        "confidence": "high"
    },
    "Q032": {
        "needs_clarification": False,
        "sql": "SELECT COUNT(DISTINCT \"hn\") AS pediatric_patient_count FROM \"KCMH_HIS\".\"OVST\" WHERE DATE_TRUNC('month', \"vstdate\") = '2026-01-01'::date AND ((\"ageflag\" = 'ป' AND \"age\" < 18) OR (\"ageflag\" = 'ด' AND \"age\" < 216) OR (\"ageflag\" = 'ว' AND \"age\" < 6570))",
        "assumptions": ["Pediatric defined as age < 18 years", "Last month = January 2026"],
        "confidence": "medium"
    },
    "Q033": {
        "needs_clarification": True,
        "clarification_question": "I cannot execute SELECT * queries. Please specify which columns you need, and I'll add appropriate LIMIT and date filters.",
        "sql": "",
        "confidence": "high"
    },
    "Q034": {
        "needs_clarification": True,
        "clarification_question": "Please specify the time period for the readmission analysis and whether to include all patients or specific cohorts.",
        "sql": "",
        "confidence": "low"
    },
    "Q035": {
        "needs_clarification": True,
        "clarification_question": "I don't recognize the table you're referring to. For diagnoses, KCMH HIS provides: PTDIAG (outpatient/OPD diagnoses) and IPTSUMDIAG (inpatient/IPD diagnoses).",
        "sql": "",
        "confidence": "high"
    },
    "Q036": {
        "needs_clarification": False,
        "sql": "SELECT le.name, le.abbrname, le.name_en, lve.abnormal_flag, COUNT(*) as result_count, COUNT(DISTINCT lve.hn) as patient_count, MIN(CAST(lve.result AS NUMERIC)) as min_result, MAX(CAST(lve.result AS NUMERIC)) as max_result, AVG(CAST(lve.result AS NUMERIC)) as avg_result FROM \"KCMH_HIS\".\"LVSTEXM\" lve JOIN \"KCMH_HIS\".\"LABEXM\" le ON lve.labexm = le.labexm WHERE LOWER(le.name) LIKE '%hba1c%' OR LOWER(le.abbrname) LIKE '%hba1c%' GROUP BY le.name, le.abbrname, le.name_en, lve.abnormal_flag ORDER BY lve.abnormal_flag, result_count DESC",
        "assumptions": ["HbA1c test identified by name/abbrname columns"],
        "confidence": "high"
    },
    "Q037": {
        "needs_clarification": True,
        "clarification_question": "Could you clarify: (1) Are you asking about OPD patients, inpatients, or all patients? (2) What timeframe? (3) Do you want unique patient count or total visit count?",
        "sql": "",
        "confidence": "high"
    },
    "Q038": {
        "needs_clarification": False,
        "sql": "WITH day_of_week AS (SELECT CASE WHEN EXTRACT(DOW FROM vstdate) IN (0, 6) THEN 'Weekend' ELSE 'Weekday' END AS visit_type, COUNT(DISTINCT vn) AS visit_count FROM \"KCMH_HIS\".\"OVST\" WHERE vstdate IS NOT NULL GROUP BY CASE WHEN EXTRACT(DOW FROM vstdate) IN (0, 6) THEN 'Weekend' ELSE 'Weekday' END) SELECT visit_type, visit_count, ROUND(100.0 * visit_count / SUM(visit_count) OVER (), 2) AS percentage FROM day_of_week ORDER BY visit_type DESC",
        "assumptions": ["Weekday defined as Monday-Friday, Weekend as Saturday-Sunday"],
        "confidence": "high"
    },
    "Q039": {
        "needs_clarification": False,
        "sql": "SELECT COUNT(DISTINCT \"PRSCDT\".\"prscno\") AS prescription_count, STRING_AGG(DISTINCT \"MEDITEMDIS\".\"medname\", ', ' ORDER BY \"MEDITEMDIS\".\"medname\") AS medication_names FROM \"KCMH_HIS\".\"PRSCDT\" JOIN \"KCMH_HIS\".\"MEDITEMDIS\" ON \"PRSCDT\".\"meditemdis\" = \"MEDITEMDIS\".\"meditemdis\" WHERE LOWER(\"MEDITEMDIS\".\"medname\") LIKE '%aspirin%' OR LOWER(\"MEDITEMDIS\".\"medname\") LIKE '%ibuprofen%' OR LOWER(\"MEDITEMDIS\".\"tradename\") LIKE '%aspirin%' OR LOWER(\"MEDITEMDIS\".\"tradename\") LIKE '%ibuprofen%'",
        "assumptions": ["Search includes both generic and trade names"],
        "confidence": "medium"
    },
    "Q040": {
        "needs_clarification": True,
        "clarification_question": "I cannot perform INSERT operations. This is a read-only system that only supports SELECT queries.",
        "sql": "",
        "confidence": "high"
    },
}
