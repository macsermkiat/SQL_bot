#!/usr/bin/env python3
"""
Run evaluation on all clinical complex batches (CQ001-CQ040).
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from tests.sql_testing.clinical_batch1_results import CLINICAL_BATCH1_RESPONSES
from tests.sql_testing.clinical_batch2_results import CLINICAL_BATCH2_RESPONSES
from tests.sql_testing.clinical_batch3_results import CLINICAL_BATCH3_RESPONSES
from tests.sql_testing.clinical_batch4_results import CLINICAL_BATCH4_RESPONSES
from tests.sql_testing.evaluator import SQLEvaluator
from tests.sql_testing.models import (
    GenerationResult,
    SQLGenerationOutput,
    TestCase,
    TestResult,
)


def load_clinical_questions() -> dict[str, TestCase]:
    """Load clinical complex test questions from JSON."""
    questions_path = project_root / "test_data" / "sql_testing" / "questions" / "clinical_complex_questions.json"
    with open(questions_path) as f:
        data = json.load(f)
    return {q["id"]: TestCase.from_dict(q) for q in data}


def evaluate_clinical_batches() -> None:
    """Evaluate all clinical complex question responses."""
    questions = load_clinical_questions()
    evaluator = SQLEvaluator()

    all_responses = {
        **CLINICAL_BATCH1_RESPONSES,
        **CLINICAL_BATCH2_RESPONSES,
        **CLINICAL_BATCH3_RESPONSES,
        **CLINICAL_BATCH4_RESPONSES,
    }

    results = []
    passed = 0
    failed = 0
    warned = 0

    failures_by_category = defaultdict(list)
    warnings_by_type = defaultdict(int)
    category_stats = defaultdict(lambda: {"pass": 0, "warn": 0, "fail": 0})

    print("=" * 80)
    print("CLINICAL COMPLEX QUESTIONS EVALUATION (CQ001-CQ040)")
    print("=" * 80)
    print()

    for qid in sorted(all_responses.keys()):
        response_data = all_responses[qid]
        test_case = questions.get(qid)

        if not test_case:
            print(f"[SKIP] {qid}: Test case not found")
            continue

        sql_output = SQLGenerationOutput(
            sql=response_data.get("sql", ""),
            needs_clarification=response_data.get("needs_clarification", False),
            clarification_question=response_data.get("clarification_question"),
            assumptions=response_data.get("assumptions", []),
            concepts_used=response_data.get("concepts_used", []),
            confidence=response_data.get("confidence", "medium"),
        )

        gen_result = GenerationResult(
            question_id=qid,
            question_text=test_case.text,
            generation_success=True,
            response=sql_output,
        )

        eval_result = evaluator.evaluate(test_case, gen_result)
        results.append((qid, test_case, eval_result, sql_output))

        # Track by category
        cat = test_case.category.value if hasattr(test_case.category, 'value') else str(test_case.category)

        if eval_result.overall_result == TestResult.PASS:
            passed += 1
            status = "\033[92mPASS\033[0m"
            category_stats[cat]["pass"] += 1
        elif eval_result.overall_result == TestResult.WARN:
            warned += 1
            status = "\033[93mWARN\033[0m"
            category_stats[cat]["warn"] += 1
            # Track warning types
            for w in eval_result.warnings:
                if "Low-confidence join" in w:
                    warnings_by_type["join_confidence"] += 1
                else:
                    warnings_by_type["other"] += 1
        else:
            failed += 1
            status = "\033[91mFAIL\033[0m"
            category_stats[cat]["fail"] += 1
            failures_by_category[eval_result.error_category or "unknown"].append(qid)

        print(f"[{status}] {qid}: {test_case.text[:55]}...")

    total = passed + failed + warned
    pass_rate = (passed / total * 100) if total > 0 else 0
    pass_warn_rate = ((passed + warned) / total * 100) if total > 0 else 0

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total:      {total}")
    print(f"Passed:     {passed} ({passed/total*100:.1f}%)")
    print(f"Warned:     {warned} ({warned/total*100:.1f}%)")
    print(f"Failed:     {failed} ({failed/total*100:.1f}%)")
    print(f"Pass Rate:  {pass_rate:.1f}%")
    print(f"Pass+Warn:  {pass_warn_rate:.1f}%")
    print()

    # Category breakdown
    print("=" * 80)
    print("RESULTS BY CATEGORY")
    print("=" * 80)
    for cat, stats in sorted(category_stats.items()):
        total_cat = stats["pass"] + stats["warn"] + stats["fail"]
        print(f"  {cat}: {stats['pass']} pass, {stats['warn']} warn, {stats['fail']} fail (total: {total_cat})")
    print()

    # Failure breakdown
    if failures_by_category:
        print("=" * 80)
        print("FAILURES BY ERROR TYPE")
        print("=" * 80)
        for cat, qids in sorted(failures_by_category.items()):
            print(f"  {cat}: {', '.join(qids)}")
        print()

    # Warning breakdown
    if warnings_by_type:
        print("=" * 80)
        print("WARNINGS BY TYPE")
        print("=" * 80)
        for wtype, count in sorted(warnings_by_type.items(), key=lambda x: -x[1]):
            print(f"  {wtype}: {count}")
        print()

    # Detailed failures
    print("=" * 80)
    print("FAILURE DETAILS")
    print("=" * 80)
    for qid, test_case, eval_result, sql_output in results:
        if eval_result.overall_result == TestResult.FAIL:
            print(f"\n{qid}: {test_case.text[:70]}...")
            cat = test_case.category.value if hasattr(test_case.category, 'value') else str(test_case.category)
            print(f"  Category: {cat}")
            print(f"  Expected: {test_case.expected_behavior.value}")
            print(f"  Actual:   {eval_result.actual_behavior}")
            print(f"  Error:    {eval_result.error_category}")

            for layer_name, layer in eval_result.layers.items():
                if not layer.passed and layer.details:
                    print(f"  [{layer_name}]: {layer.details}")

            if sql_output.sql:
                sql_preview = sql_output.sql.replace('\n', ' ')[:120]
                print(f"  SQL: {sql_preview}...")


if __name__ == "__main__":
    evaluate_clinical_batches()
