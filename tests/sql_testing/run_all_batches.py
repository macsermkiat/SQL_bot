#!/usr/bin/env python3
"""
Run evaluation on all batches and generate summary.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from tests.sql_testing.batch1_results import BATCH1_RESPONSES
from tests.sql_testing.batch2_results import BATCH2_RESPONSES
from tests.sql_testing.batch3_results import BATCH3_RESPONSES
from tests.sql_testing.batch4_results import BATCH4_RESPONSES
from tests.sql_testing.batch5_results import BATCH5_RESPONSES
from tests.sql_testing.batch6_results import BATCH6_RESPONSES
from tests.sql_testing.evaluator import SQLEvaluator
from tests.sql_testing.models import (
    GenerationResult,
    SQLGenerationOutput,
    TestCase,
    TestResult,
)


def load_questions() -> dict[str, TestCase]:
    """Load test questions from JSON."""
    questions_path = project_root / "test_data" / "sql_testing" / "questions" / "base_questions.json"
    with open(questions_path) as f:
        data = json.load(f)
    return {q["id"]: TestCase.from_dict(q) for q in data}


def evaluate_all() -> None:
    """Evaluate all responses from both batches."""
    questions = load_questions()
    evaluator = SQLEvaluator()

    all_responses = {
        **BATCH1_RESPONSES,
        **BATCH2_RESPONSES,
        **BATCH3_RESPONSES,
        **BATCH4_RESPONSES,
        **BATCH5_RESPONSES,
        **BATCH6_RESPONSES,
    }

    results = []
    passed = 0
    failed = 0
    warned = 0

    failures_by_category = defaultdict(list)
    warnings_by_type = defaultdict(int)

    print("=" * 80)
    print("COMBINED BATCH EVALUATION (Q001-Q060)")
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

        if eval_result.overall_result == TestResult.PASS:
            passed += 1
            status = "\033[92mPASS\033[0m"
        elif eval_result.overall_result == TestResult.WARN:
            warned += 1
            status = "\033[93mWARN\033[0m"
            # Track warning types
            for w in eval_result.warnings:
                if "Low-confidence join" in w:
                    warnings_by_type["join_confidence"] += 1
                else:
                    warnings_by_type["other"] += 1
        else:
            failed += 1
            status = "\033[91mFAIL\033[0m"
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

    # Failure breakdown
    if failures_by_category:
        print("=" * 80)
        print("FAILURES BY CATEGORY")
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
            print(f"  Category: {test_case.category.value}")
            print(f"  Expected: {test_case.expected_behavior.value}")
            print(f"  Actual:   {eval_result.actual_behavior}")
            print(f"  Error:    {eval_result.error_category}")

            for layer_name, layer in eval_result.layers.items():
                if not layer.passed and layer.details:
                    print(f"  [{layer_name}]: {layer.details}")

            if sql_output.sql:
                sql_preview = sql_output.sql.replace('\n', ' ')[:120]
                print(f"  SQL: {sql_preview}...")

    # Recommendations
    print()
    print("=" * 80)
    print("RECOMMENDATIONS")
    print("=" * 80)

    if "syntax_error" in failures_by_category:
        print("\n1. SYNTAX ERRORS:")
        print("   - Add explicit PostgreSQL syntax rules to prompts")
        print("   - Use LIMIT instead of TOP, EXTRACT instead of YEAR()")
        print("   - Affected: " + ", ".join(failures_by_category.get("syntax_error", [])))

    if "schema_error" in failures_by_category:
        print("\n2. SCHEMA ERRORS:")
        print("   - IPT uses 'rgtdate' not 'admdate' for admission date")
        print("   - Update subagent prompts with correct column names")
        print("   - Affected: " + ", ".join(failures_by_category.get("schema_error", [])))

    if warnings_by_type.get("join_confidence", 0) > 3:
        print("\n3. JOIN CONFIDENCE WARNINGS:")
        print("   - Many valid SQL queries have low-confidence join warnings")
        print("   - Consider treating these as informational, not warnings")
        print("   - Update join_edges.csv with verified join paths")


if __name__ == "__main__":
    evaluate_all()
