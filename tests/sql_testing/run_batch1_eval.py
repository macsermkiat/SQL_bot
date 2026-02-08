#!/usr/bin/env python3
"""
Run evaluation on Batch 1 (Q001-Q010) results.

Evaluates subagent responses using local evaluator (no API calls).
"""

import json
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from tests.sql_testing.batch1_results import BATCH1_RESPONSES
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


def evaluate_batch() -> None:
    """Evaluate all batch 1 responses."""
    questions = load_questions()
    evaluator = SQLEvaluator()

    results = []
    passed = 0
    failed = 0
    warned = 0

    print("=" * 70)
    print("BATCH 1 EVALUATION (Q001-Q010)")
    print("=" * 70)
    print()

    for qid in sorted(BATCH1_RESPONSES.keys()):
        response_data = BATCH1_RESPONSES[qid]
        test_case = questions.get(qid)

        if not test_case:
            print(f"[SKIP] {qid}: Test case not found")
            continue

        # Create generation result
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

        # Evaluate
        eval_result = evaluator.evaluate(test_case, gen_result)
        results.append((qid, test_case, eval_result, sql_output))

        # Count results
        if eval_result.overall_result == TestResult.PASS:
            passed += 1
            status = "\033[92mPASS\033[0m"
        elif eval_result.overall_result == TestResult.WARN:
            warned += 1
            status = "\033[93mWARN\033[0m"
        else:
            failed += 1
            status = "\033[91mFAIL\033[0m"

        # Print result
        print(f"[{status}] {qid}: {test_case.text[:50]}...")
        print(f"       Expected: {test_case.expected_behavior.value}")
        print(f"       Actual:   {eval_result.actual_behavior}")

        if not eval_result.behavior_match:
            print(f"       MISMATCH!")

        if eval_result.warnings:
            for w in eval_result.warnings[:2]:
                print(f"       Warning: {w[:60]}...")

        if eval_result.suggestions:
            for s in eval_result.suggestions[:2]:
                print(f"       Suggestion: {s[:60]}...")

        # Show error details for failures
        if eval_result.overall_result == TestResult.FAIL:
            for layer_name, layer in eval_result.layers.items():
                if not layer.passed and layer.details:
                    print(f"       {layer_name}: {layer.details[:80]}...")

        print()

    # Summary
    total = passed + failed + warned
    pass_rate = (passed / total * 100) if total > 0 else 0

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total:  {total}")
    print(f"Passed: {passed} ({passed/total*100:.1f}%)")
    print(f"Warned: {warned} ({warned/total*100:.1f}%)")
    print(f"Failed: {failed} ({failed/total*100:.1f}%)")
    print(f"Pass Rate: {pass_rate:.1f}%")
    print()

    # Failure analysis
    if failed > 0:
        print("=" * 70)
        print("FAILURE ANALYSIS")
        print("=" * 70)
        for qid, test_case, eval_result, sql_output in results:
            if eval_result.overall_result == TestResult.FAIL:
                print(f"\n{qid}: {test_case.text[:60]}...")
                print(f"  Category: {test_case.category.value}")
                print(f"  Expected: {test_case.expected_behavior.value}")
                print(f"  Actual: {eval_result.actual_behavior}")
                print(f"  Error: {eval_result.error_category}")

                # Show SQL snippet if available
                if sql_output.sql:
                    sql_preview = sql_output.sql.replace('\n', ' ')[:100]
                    print(f"  SQL: {sql_preview}...")

                # Show layer details
                for layer_name, layer in eval_result.layers.items():
                    if not layer.passed:
                        print(f"  Layer [{layer_name}]: {layer.details}")


if __name__ == "__main__":
    evaluate_batch()
