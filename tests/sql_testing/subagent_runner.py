"""
SQL Testing with Claude Code Subagents.

Uses Task tool to spawn subagents for SQL generation,
then evaluates results locally without API calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from tests.sql_testing.evaluator import SQLEvaluator
from tests.sql_testing.models import (
    EvaluationResult,
    GenerationResult,
    SQLGenerationOutput,
    TestCase,
    TestResult,
    TestRunReport,
    TestRunSummary,
)


# Minimal schema context for subagent prompts
SCHEMA_CONTEXT = """
## POSTGRESQL SYNTAX (CRITICAL)
- Use LIMIT N at end (NOT "TOP N" which is SQL Server)
- Use EXTRACT(YEAR FROM date) (NOT YEAR(date))
- Use EXTRACT(MONTH FROM date) (NOT MONTH(date))
- Use double quotes for identifiers: "KCMH_HIS"."TABLE"."column"

## KEY TABLES (Use "KCMH_HIS"."TABLE" format with double quotes)

### Visit/Admission Tables
- OVST: OPD visits. PK: vn. Columns: vn, hn, vstdate, vsttime, cliniclct, dct, age, emrgncy, an
  NOTE: OVST does NOT have a "pttype" column. Insurance/pttype lives on ARPT, PRSC, PRSCDT, INCPT, PTOPRT, IPTADM — not OVST.
- IPT: Inpatient admissions. PK: an. Columns: an, hn, vn, rgtdate (NOT admdate!), dchdate, ward, dchst, indate, outdate
  NOTE: Use "rgtdate" for admission/registration date, NOT "admdate"
- PTDIAG: OPD diagnoses. Columns: vn, hn, icd10, diagtype
- IPTSUMDIAG: IPD diagnoses. Columns: an, icd10, diagtype

### Lab Tables
- LVST: Lab orders. PK: labno. Columns: labno, vn, hn, lvstdate, labgrp
- LVSTEXM: Lab results. Columns: labno, hn, labexm, result, lvstdate, minnrm, maxnrm, nrmunit
- LABEXM: Lab test master. PK: labexm. Columns: labexm, name, abbrname, labgrp

### Prescription Tables
- PRSC: Prescriptions. PK: prscno. Columns: prscno, vn, hn, prscdate, dct
- PRSCDT: Prescription items. Columns: prscno, meditem, qty, prscst[numeric]
  NOTE: Column is "meditem" NOT "meditemdis"
- MEDITEMDIS: Drug master. PK: meditem. Columns: meditem, medname, tradename, chemname, prscname
  NOTE: PK is "meditem" NOT "meditemdis"

### Procedure Tables
- IPTSUMOPRT: IPD procedures. Columns: an, icd9cm, oprtcnt, oprtside, orflag (5 columns only)
  CRITICAL: IPTSUMOPRT has NO date column. To filter by procedure date,
  join to IPT on "an" and use IPT.rgtdate (admission) or IPT.dchdate (discharge).
  ICD-9-CM codes are stored WITHOUT dots: craniotomy '0124', appendectomy '4709' (use LIKE '470%').
- PTICD9CM: OPD procedures. Columns: vn, icd9cm, cliniclct
- ICD9CM: Procedure master. PK: icd9cm. Columns: icd9cm, name, thainame

### Reference Tables (names are NOT PHI)
- CLINICLCT: Clinics. PK: cliniclct. Columns: cliniclct, name, clinictype
- DCT: Doctors. PK: dct. Columns: dct, fname, lname, spclty
- ICD10: Diagnoses. PK: icd10. Columns: icd10, name, thainame
- PTTYPE: Patient types. PK: pttype. Columns: pttype, name
- WARD: Wards. PK: ward. Columns: ward, name

## COLUMN CORRECTIONS (Common Mistakes)
- Use CLINICLCT.name (NOT cliniclctnm)
- Use LABEXM.name (NOT labexmnm)
- Use LVST.lvstdate (NOT vstdate) for lab date
- Use LVSTEXM.result (NOT labresult)
- PRSC has NO cliniclct column - join via OVST.vn
- IPT uses rgtdate (NOT admdate) for admission date
- IPT has NO age column - calculate from patient birthdate if needed
- PRSCDT uses meditem (NOT meditemdis) for drug FK
- MEDITEMDIS PK is meditem (NOT meditemdis)
- IPTSUMOPRT has NO date column - JOIN to IPT on "an" and filter on IPT.rgtdate/IPT.dchdate
- OVST has NO pttype column - use ARPT.pttype (or PRSC/PRSCDT/INCPT) for insurance-type queries

## JOIN PATTERNS
- Visits to clinic: OVST.cliniclct = CLINICLCT.cliniclct
- Prescriptions to patient: PRSC.hn links to other tables via hn
- Prescription items: PRSC.prscno = PRSCDT.prscno AND PRSC.sphmlct = PRSCDT.sphmlct
  (join on BOTH keys; prvno is an authorization ref, NOT a join key)
- Drug lookup: PRSCDT.meditem = MEDITEMDIS.meditem (NOT meditemdis!)
- Labs order: LVST.labno = LVSTEXM.labno
- Lab test lookup: LVSTEXM.labexm = LABEXM.labexm
- OPD Diagnoses: OVST.vn = PTDIAG.vn, PTDIAG.icd10 = ICD10.icd10
- IPD Diagnoses: IPT.an = IPTSUMDIAG.an
- IPD Procedures: IPT.an = IPTSUMOPRT.an (use IPT.rgtdate for date filter)
- Procedure lookup: IPTSUMOPRT.icd9cm = ICD9CM.icd9cm
- Insurance types: ARPT.pttype = PTTYPE.pttype (ARPT is one row per visit/charge)

## CRITICAL JOIN PATTERNS FOR COMPLEX QUERIES
- Drug + Diagnosis (same patient): Join via hn
  PRSC.hn = PTDIAG.hn (then filter PRSC -> PRSCDT -> MEDITEMDIS for drug)
- Drug + Lab (same patient): Join via hn
  PRSC.hn = LVSTEXM.hn (then filter drug and lab test)
- Procedure + Diagnosis (IPD): Join via an
  IPTSUMOPRT.an = IPTSUMDIAG.an = IPT.an

## DATA TYPES (CRITICAL)
- prscst, pttype, cliniclct, ward, dct, labexm, meditem are [numeric] - use integers, NOT strings
- icd10, icd9cm, hn, an are [text]
- vstdate, prscdate, lvstdate, rgtdate, dchdate are [date] - use 'YYYY-MM-DD' format
- result in LVSTEXM is [text] - cast to numeric for comparisons: CAST(result AS NUMERIC)
"""

CONCEPTS_CONTEXT = """
## CLINICAL CONCEPTS

### Common Diagnoses (ICD-10)
- Diabetes: E10-E14 (E10=Type1, E11=Type2, E13=Other, E14=Unspecified)
- Hypertension: I10-I15
- Heart failure: I50
- Atrial fibrillation: I48
- Coronary artery disease/IHD: I20-I25
- STEMI: I21
- Stroke: I60-I69 (I60-I62=hemorrhagic, I63=ischemic)
- Pneumonia: J12-J18
- COPD: J44
- Asthma: J45-J46
- CKD (chronic kidney disease): N18
- Liver cirrhosis: K74
- Hepatitis: B15-B19
- Epilepsy: G40-G41
- Parkinson: G20
- Schizophrenia: F20
- Rheumatoid arthritis: M05-M06
- Osteoarthritis: M15-M19 (M16=hip, M17=knee)
- Gout: M10
- HIV/AIDS: B20-B24
- Leukemia: C91-C95
- Breast cancer: C50
- Colorectal cancer: C18-C20
- Prostate cancer: C61
- Thyroid cancer: C73
- Meningioma: D32
- Obesity: E66
- Preeclampsia: O14
- Cholecystitis: K81
- GI bleeding: K92.0-K92.2
- Anemia: D50-D64

### Common Procedures (ICD-9-CM)
- Craniotomy: 01.24
- CABG: 36.1x
- PCI/Angioplasty: 36.06-36.07
- Coronary angiography: 88.55-88.57
- Hip replacement: 81.51-81.52
- Knee replacement: 81.54
- Cholecystectomy: 51.22-51.23
- Appendectomy: 47.0
- Colectomy: 45.7-45.8
- Mastectomy: 85.41-85.48
- Thyroidectomy: 06.2-06.5
- Prostatectomy: 60.5
- Cesarean section: 74.0-74.4
- Mechanical ventilation: 96.7

### Common Drug Names (search MEDITEMDIS.medname or tradename)
- Anticoagulants: warfarin, coumadin, rivaroxaban, dabigatran, apixaban
- Antiplatelets: aspirin, clopidogrel, plavix
- Statins: atorvastatin, lipitor, simvastatin, rosuvastatin
- Diabetes: metformin, insulin, novorapid, lantus, humalog
- Anti-seizure: phenytoin, dilantin, carbamazepine, tegretol, valproate
- Heart: amiodarone, cordarone, digoxin, lanoxin, furosemide, lasix
- ACE inhibitors: enalapril, lisinopril, ramipril, captopril
- Immunosuppressants: methotrexate, tacrolimus, prograf, cyclosporine
- Psychiatric: clozapine, clozaril, lithium
- Diuretics: spironolactone, aldactone
- Gout: allopurinol
- Erythropoietin: epoetin, darbepoetin
- Antiretrovirals: efavirenz, tenofovir, lamivudine
- Biologics: adalimumab, etanercept, infliximab, tocilizumab
- Inhaled steroids: budesonide, fluticasone, beclomethasone

### Lab Tests (search LABEXM.name or abbrname)
- Lipid panel: LDL, HDL, Cholesterol, Triglyceride
- Diabetes: HbA1c, Glucose, FBS
- Kidney: BUN, Creatinine, eGFR, Potassium, Sodium
- Liver: AST, ALT, ALP, Bilirubin, Albumin
- CBC: WBC, Hb, Hct, Platelet, ANC, Neutrophil
- Thyroid: TSH, FT3, FT4
- Coagulation: INR, PT, PTT
- Cardiac: Troponin, BNP, CK-MB
- Uric acid
- Drug levels: Lithium, Phenytoin, Digoxin
- HIV viral load
- PSA (prostate)
- Estrogen receptor, ER

### Lab Thresholds (Common Clinical Cutoffs)
- LDL high: > 190 mg/dL (very high risk)
- HbA1c uncontrolled: > 9%
- INR high bleeding risk: > 4.0
- Potassium high (hyperkalemia): > 5.5
- Sodium low (hyponatremia): < 130
- ALT elevated (3x ULN): > 120
- Creatinine elevated: > 1.5 or 50% increase
- WBC low (neutropenia): < 3000
- ANC severe neutropenia: < 500
- Glucose hypoglycemia: < 70
- Uric acid target: < 6
"""


def build_subagent_prompt(question: str, question_id: str) -> str:
    """Build the prompt for a SQL generation subagent."""
    from datetime import datetime
    import zoneinfo

    bangkok_tz = zoneinfo.ZoneInfo("Asia/Bangkok")
    now = datetime.now(bangkok_tz)
    current_date = now.strftime("%Y-%m-%d")
    current_year = now.year
    last_year = current_year - 1

    return f"""You are a SQL expert for KCMH Hospital Information System.
Generate safe, read-only SQL for this question.

## QUESTION [{question_id}]
{question}

## CRITICAL RULES
1. SELECT ONLY - no INSERT/UPDATE/DELETE
2. NO PHI IN OUTPUT - never SELECT hn, fname, lname, phone, address, dob
3. Use PHI columns ONLY for JOINs/WHERE, NOT in SELECT
4. AGGREGATE by default - COUNT, SUM, AVG preferred
5. Require LIMIT for non-aggregate queries (max 2000)
6. Use "KCMH_HIS"."TABLE"."column" format with double quotes

## REFUSE PHI REQUESTS
If asked for patient names/HN/phone/address, set needs_clarification=true with message explaining privacy.

{SCHEMA_CONTEXT}

{CONCEPTS_CONTEXT}

## DATES
- Current date: {current_date}
- Current year: {current_year}
- Last year: {last_year}

## OUTPUT FORMAT (JSON only)
```json
{{
  "needs_clarification": false,
  "clarification_question": null,
  "sql": "SELECT ... FROM \"KCMH_HIS\".\"TABLE\" WHERE ...",
  "assumptions": ["list assumptions made"],
  "concepts_used": ["concept_name"],
  "confidence": "high|medium|low"
}}
```

If the question asks for PHI output:
```json
{{
  "needs_clarification": true,
  "clarification_question": "I cannot provide patient-level identifiable information (names, HN, etc.) due to privacy. I can provide aggregate counts instead.",
  "sql": "",
  "confidence": "high"
}}
```

Generate the response now (JSON only, no markdown fences in the JSON itself):
"""


def parse_subagent_response(response_text: str) -> SQLGenerationOutput:
    """Parse the subagent response into SQLGenerationOutput."""
    try:
        # Handle markdown code blocks
        text = response_text.strip()
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            text = text[start:end].strip()

        data = json.loads(text)
        return SQLGenerationOutput.from_dict(data)
    except (json.JSONDecodeError, ValueError) as e:
        return SQLGenerationOutput(
            needs_clarification=True,
            clarification_question=f"Parse error: {e}",
            confidence="low",
        )


@dataclass
class SubagentTestRunner:
    """
    Test runner using Claude Code subagents.

    Generates SQL via subagents and evaluates locally.
    """

    evaluator: SQLEvaluator = field(default_factory=SQLEvaluator)
    results: dict[str, EvaluationResult] = field(default_factory=dict)
    generation_results: dict[str, GenerationResult] = field(default_factory=dict)

    def prepare_test_batch(
        self,
        questions: list[TestCase],
    ) -> list[dict[str, Any]]:
        """
        Prepare a batch of questions for subagent testing.

        Returns list of dicts with question info and prompts.
        """
        batch = []
        for q in questions:
            prompt = build_subagent_prompt(q.text, q.id)
            batch.append({
                "id": q.id,
                "text": q.text,
                "prompt": prompt,
                "test_case": q,
            })
        return batch

    def process_subagent_result(
        self,
        question_id: str,
        question_text: str,
        response_text: str,
        test_case: TestCase,
    ) -> tuple[GenerationResult, EvaluationResult]:
        """
        Process a subagent response and evaluate it.

        Args:
            question_id: Question ID
            question_text: Original question text
            response_text: Raw response from subagent
            test_case: The test case

        Returns:
            Tuple of (GenerationResult, EvaluationResult)
        """
        # Parse response
        parsed = parse_subagent_response(response_text)

        gen_result = GenerationResult(
            question_id=question_id,
            question_text=question_text,
            generation_success=True,
            response=parsed,
        )

        # Evaluate
        eval_result = self.evaluator.evaluate(test_case, gen_result)

        # Store results
        self.results[question_id] = eval_result
        self.generation_results[question_id] = gen_result

        return gen_result, eval_result

    def get_summary(self) -> TestRunSummary:
        """Get summary statistics from all results."""
        summary = TestRunSummary()
        summary.total = len(self.results)

        for result in self.results.values():
            if result.overall_result == TestResult.PASS:
                summary.passed += 1
            elif result.overall_result == TestResult.FAIL:
                summary.failed += 1
            elif result.overall_result == TestResult.WARN:
                summary.warned += 1
            elif result.overall_result == TestResult.SKIP:
                summary.skipped += 1

            # Track by category
            cat = result.expected_behavior.value
            if cat not in summary.by_category:
                summary.by_category[cat] = {"pass": 0, "fail": 0, "warn": 0}
            if result.overall_result == TestResult.PASS:
                summary.by_category[cat]["pass"] += 1
            elif result.overall_result == TestResult.FAIL:
                summary.by_category[cat]["fail"] += 1
            else:
                summary.by_category[cat]["warn"] += 1

            # Track error categories
            if result.error_category:
                summary.error_categories[result.error_category] = (
                    summary.error_categories.get(result.error_category, 0) + 1
                )

        summary.calculate_pass_rate()
        return summary

    def get_failures(self) -> list[tuple[str, EvaluationResult, GenerationResult]]:
        """Get all failed test cases with their results."""
        failures = []
        for qid, result in self.results.items():
            if result.overall_result == TestResult.FAIL:
                gen = self.generation_results.get(qid)
                failures.append((qid, result, gen))
        return failures

    def get_report(self, run_id: str | None = None) -> TestRunReport:
        """Generate a complete test report."""
        if run_id is None:
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        return TestRunReport(
            run_id=run_id,
            started_at=datetime.now(),
            completed_at=datetime.now(),
            summary=self.get_summary(),
            results=list(self.results.values()),
        )

    def format_results_table(self) -> str:
        """Format results as a markdown table."""
        lines = ["| ID | Result | Behavior | Notes |", "|---|---|---|---|"]

        for qid, result in sorted(self.results.items()):
            status = result.overall_result.value
            behavior = result.actual_behavior or "?"
            notes = ""

            if result.warnings:
                notes = result.warnings[0][:40] + "..." if len(result.warnings[0]) > 40 else result.warnings[0]
            elif result.suggestions:
                notes = result.suggestions[0][:40] + "..." if len(result.suggestions[0]) > 40 else result.suggestions[0]

            lines.append(f"| {qid} | {status} | {behavior} | {notes} |")

        return "\n".join(lines)


def load_questions(path: str | Path) -> list[TestCase]:
    """Load test questions from JSON file."""
    path = Path(path)
    with open(path) as f:
        data = json.load(f)
    return [TestCase.from_dict(q) for q in data]


def create_runner() -> SubagentTestRunner:
    """Create a new test runner instance."""
    return SubagentTestRunner()
