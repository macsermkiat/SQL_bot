"""Batch 5 Results: Q041-Q050"""

BATCH5_RESPONSES = {
    "Q041": {
        "needs_clarification": False,
        "sql": "SELECT m.\"meditemdis\", m.\"medname\", m.\"tradename\", COUNT(p.\"prscno\") as \"prescription_count\" FROM \"KCMH_HIS\".\"PRSCDT\" p JOIN \"KCMH_HIS\".\"MEDITEMDIS\" m ON p.\"meditemdis\" = m.\"meditemdis\" GROUP BY m.\"meditemdis\", m.\"medname\", m.\"tradename\" ORDER BY \"prescription_count\" DESC LIMIT 10",
        "assumptions": ["Counting prescription items per drug"],
        "confidence": "high"
    },
    "Q042": {
        "needs_clarification": False,
        "sql": "WITH pneumonia_cases AS (SELECT ipt.an, ipt.hn, ipt.rgtdate, ipt.dchdate, ipt.dchst, CASE WHEN ipt.dchst IN ('D', '4') THEN 1 ELSE 0 END AS died FROM \"KCMH_HIS\".\"IPT\" ipt INNER JOIN \"KCMH_HIS\".\"IPTSUMDIAG\" diag ON ipt.an = diag.an WHERE diag.icd10 BETWEEN 'J12' AND 'J18' AND diag.diagtype IN ('1', '2')) SELECT COUNT(*) AS total_pneumonia_admissions, SUM(died) AS deaths, ROUND(100.0 * SUM(died) / COUNT(*), 2) AS mortality_rate_percent FROM pneumonia_cases",
        "assumptions": ["Discharge status 'D' or '4' indicates death", "Pneumonia ICD-10 codes J12-J18"],
        "confidence": "medium"
    },
    "Q043": {
        "needs_clarification": True,
        "clarification_question": "What defines 'abnormal'? The LVSTEXM table has an abnormal_flag column. Would you like to filter by specific abnormal values (U or L)?",
        "sql": "",
        "confidence": "medium"
    },
    "Q044": {
        "needs_clarification": False,
        "sql": "SELECT CASE WHEN \"age\" < 1 THEN '0-1' WHEN \"age\" < 5 THEN '1-5' WHEN \"age\" < 18 THEN '5-18' WHEN \"age\" < 30 THEN '18-30' WHEN \"age\" < 45 THEN '30-45' WHEN \"age\" < 60 THEN '45-60' WHEN \"age\" < 75 THEN '60-75' ELSE '75+' END AS age_range, COUNT(*) AS patient_count FROM \"KCMH_HIS\".\"OVST\" WHERE \"age\" IS NOT NULL GROUP BY age_range ORDER BY age_range",
        "assumptions": ["Age distribution from OPD visits", "Grouped by age ranges"],
        "confidence": "high"
    },
    "Q045": {
        "needs_clarification": True,
        "clarification_question": "I cannot return patient identifiers (HN, names). These are protected health information.",
        "sql": "",
        "confidence": "high"
    },
    "Q046": {
        "needs_clarification": False,
        "sql": "SELECT c.\"cliniclct\", c.\"name\" AS department_name, COUNT(p.\"icd9cm\") AS procedure_count FROM \"KCMH_HIS\".\"PTICD9CM\" p JOIN \"KCMH_HIS\".\"CLINICLCT\" c ON p.\"cliniclct\" = c.\"cliniclct\" GROUP BY c.\"cliniclct\", c.\"name\" ORDER BY procedure_count DESC",
        "assumptions": ["Procedures recorded in PTICD9CM with ICD9CM codes"],
        "confidence": "high"
    },
    "Q047": {
        "needs_clarification": True,
        "clarification_question": "Wait time cannot be calculated from available data. The schema has vstdate/vsttime but no check-in or consultation start times.",
        "sql": "",
        "confidence": "high"
    },
    "Q048": {
        "needs_clarification": False,
        "sql": "SELECT COUNT(*) AS kidney_function_tests_ordered FROM \"KCMH_HIS\".\"LVSTEXM\" INNER JOIN \"KCMH_HIS\".\"LABEXM\" ON \"KCMH_HIS\".\"LVSTEXM\".\"labexm\" = \"KCMH_HIS\".\"LABEXM\".\"labexm\" WHERE (\"KCMH_HIS\".\"LABEXM\".\"name\" ILIKE '%BUN%' OR \"KCMH_HIS\".\"LABEXM\".\"name\" ILIKE '%Creatinine%' OR \"KCMH_HIS\".\"LABEXM\".\"name\" ILIKE '%eGFR%')",
        "assumptions": ["Kidney function tests include: BUN, Creatinine, eGFR"],
        "concepts_used": ["kidney_function"],
        "confidence": "medium"
    },
    "Q049": {
        "needs_clarification": True,
        "clarification_question": "The question is ambiguous. Please clarify: (1) TIME WINDOW, (2) VISIT TYPE, (3) OUTPUT FORMAT.",
        "sql": "",
        "confidence": "low"
    },
    "Q050": {
        "needs_clarification": True,
        "clarification_question": "I cannot perform TRUNCATE operations. This is a read-only system.",
        "sql": "",
        "confidence": "high"
    },
}
