"""
SQL Test Orchestrator - Main entry point for the testing pipeline.

Coordinates the 4-agent pipeline:
1. Load/generate test questions
2. Generate SQL for each question
3. Evaluate generated SQL
4. Collect results and generate reports

Usage:
    uv run python -m tests.sql_testing.orchestrator --mode full
    uv run python -m tests.sql_testing.orchestrator --question Q042
    uv run python -m tests.sql_testing.orchestrator --category aggregate
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from tests.sql_testing.models import (
    Category,
    EvaluationResult,
    GenerationResult,
    PatchSuggestion,
    Severity,
    SQLGenerationOutput,
    TestCase,
    TestResult,
    TestRunReport,
    TestRunSummary,
)
from tests.sql_testing.evaluator import SQLEvaluator

if TYPE_CHECKING:
    from app.schema_catalog import SchemaCatalog

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# Default paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
TEST_DATA_DIR = PROJECT_ROOT / "test_data" / "sql_testing"
QUESTIONS_DIR = TEST_DATA_DIR / "questions"
RESULTS_DIR = TEST_DATA_DIR / "results"
PATCHES_DIR = TEST_DATA_DIR / "patches"
REPORTS_DIR = TEST_DATA_DIR / "reports"


class SQLTestOrchestrator:
    """
    Orchestrates the SQL testing pipeline.

    Coordinates question loading, SQL generation, evaluation,
    and report generation.
    """

    def __init__(
        self,
        questions_path: Path | None = None,
        results_dir: Path | None = None,
        catalog: SchemaCatalog | None = None,
    ) -> None:
        """
        Initialize orchestrator.

        Args:
            questions_path: Path to questions JSON file
            results_dir: Directory for test results
            catalog: Schema catalog for validation
        """
        self._questions_path = questions_path or QUESTIONS_DIR / "base_questions.json"
        self._results_dir = results_dir or RESULTS_DIR
        self._catalog = catalog
        self._evaluator: SQLEvaluator | None = None

    @property
    def evaluator(self) -> SQLEvaluator:
        """Get or create evaluator."""
        if self._evaluator is None:
            self._evaluator = SQLEvaluator(self._catalog)
        return self._evaluator

    def load_questions(self, path: Path | None = None) -> list[TestCase]:
        """
        Load test questions from JSON file.

        Args:
            path: Path to questions file. Uses default if None.

        Returns:
            List of TestCase objects
        """
        file_path = path or self._questions_path
        if not file_path.exists():
            logger.warning(f"Questions file not found: {file_path}")
            return []

        with open(file_path) as f:
            data = json.load(f)

        questions = []
        for item in data:
            try:
                questions.append(TestCase.from_dict(item))
            except (KeyError, ValueError) as e:
                logger.warning(f"Failed to parse question {item.get('id', '?')}: {e}")

        logger.info(f"Loaded {len(questions)} questions from {file_path}")
        return questions

    def run_sql_generation(self, question: TestCase) -> GenerationResult:
        """
        Generate SQL for a single test question.

        Args:
            question: The test case to generate SQL for

        Returns:
            GenerationResult with SQL or error
        """
        start_time = time.time()

        try:
            from app.sql_gen import get_sql_generator

            generator = get_sql_generator()
            response = generator.generate(question.text)

            elapsed_ms = (time.time() - start_time) * 1000

            return GenerationResult(
                question_id=question.id,
                question_text=question.text,
                generation_success=True,
                response=SQLGenerationOutput(
                    sql=response.sql,
                    needs_clarification=response.needs_clarification,
                    clarification_question=response.clarification_question,
                    clarified_question=response.clarified_question,
                    assumptions=response.assumptions,
                    concepts_used=response.concepts_used,
                    validation_checks=response.validation_checks,
                    answer_plan=response.answer_plan,
                    confidence=response.confidence,
                ),
                generation_time_ms=elapsed_ms,
            )

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error(f"Generation failed for {question.id}: {e}")
            return GenerationResult(
                question_id=question.id,
                question_text=question.text,
                generation_success=False,
                error=str(e),
                generation_time_ms=elapsed_ms,
            )

    def evaluate_sql(
        self,
        test_case: TestCase,
        generation: GenerationResult,
    ) -> EvaluationResult:
        """
        Evaluate generated SQL for a test case.

        Args:
            test_case: The test case
            generation: The generation result

        Returns:
            EvaluationResult with validation results
        """
        return self.evaluator.evaluate(test_case, generation)

    def run_pipeline(
        self,
        questions: list[TestCase] | None = None,
        question_ids: list[str] | None = None,
        categories: list[Category] | None = None,
        delay_seconds: float = 2.0,
    ) -> TestRunReport:
        """
        Run the full testing pipeline.

        Args:
            questions: Optional list of questions to test
            question_ids: Optional filter by question IDs
            categories: Optional filter by categories

        Returns:
            TestRunReport with all results
        """
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        started_at = datetime.now()

        logger.info(f"Starting test run: {run_id}")

        # Load questions if not provided
        if questions is None:
            questions = self.load_questions()

        # Filter by IDs if specified
        if question_ids:
            questions = [q for q in questions if q.id in question_ids]

        # Filter by categories if specified
        if categories:
            questions = [q for q in questions if q.category in categories]

        if not questions:
            logger.warning("No questions to test")
            return TestRunReport(
                run_id=run_id,
                started_at=started_at,
                completed_at=datetime.now(),
            )

        logger.info(f"Testing {len(questions)} questions")

        # Initialize report
        report = TestRunReport(
            run_id=run_id,
            started_at=started_at,
        )

        # Process each question
        for i, question in enumerate(questions, 1):
            logger.info(f"[{i}/{len(questions)}] Testing {question.id}: {question.text[:50]}...")

            try:
                # Generate SQL
                generation = self.run_sql_generation(question)

                # Evaluate
                evaluation = self.evaluate_sql(question, generation)

                # Add to report
                report.results.append(evaluation)

                # Log result
                status = evaluation.overall_result.value
                logger.info(f"  -> {status}")
            except Exception as e:
                # Handle unexpected errors gracefully
                logger.error(f"  -> ERROR: {e}")
                error_result = EvaluationResult(
                    question_id=question.id,
                    expected_behavior=question.expected_behavior,
                    actual_behavior="error",
                    overall_result=TestResult.FAIL,
                    error_details=f"Pipeline error: {e}",
                )
                report.results.append(error_result)

            # Rate limiting delay (skip for last question)
            if i < len(questions) and delay_seconds > 0:
                time.sleep(delay_seconds)

        # Generate summary
        report.summary = self._generate_summary(report.results)
        report.completed_at = datetime.now()

        # Save results
        self._save_report(report)

        # Log summary
        self._log_summary(report)

        return report

    def _generate_summary(
        self,
        results: list[EvaluationResult],
    ) -> TestRunSummary:
        """Generate summary statistics from results."""
        summary = TestRunSummary(total=len(results))

        for result in results:
            if result.overall_result == TestResult.PASS:
                summary.passed += 1
            elif result.overall_result == TestResult.FAIL:
                summary.failed += 1
            elif result.overall_result == TestResult.WARN:
                summary.warned += 1
            elif result.overall_result == TestResult.SKIP:
                summary.skipped += 1

            # Track by severity
            if result.severity:
                severity_key = result.severity.value
                summary.by_severity[severity_key] = (
                    summary.by_severity.get(severity_key, 0) + 1
                )

            # Track error categories
            if result.error_category:
                summary.error_categories[result.error_category] = (
                    summary.error_categories.get(result.error_category, 0) + 1
                )

        summary.calculate_pass_rate()
        return summary

    def _save_report(self, report: TestRunReport) -> Path:
        """Save report to results directory."""
        run_dir = self._results_dir / f"run_{report.run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)

        # Save full report as JSON
        report_path = run_dir / "report.json"
        with open(report_path, "w") as f:
            json.dump(report.to_dict(), f, indent=2)

        # Save markdown summary
        md_path = run_dir / "summary.md"
        with open(md_path, "w") as f:
            f.write(self._generate_markdown_report(report))

        logger.info(f"Report saved to {run_dir}")
        return run_dir

    def _generate_markdown_report(self, report: TestRunReport) -> str:
        """Generate markdown summary report."""
        lines = [
            f"# SQL Test Run Report: {report.run_id}",
            "",
            f"**Started:** {report.started_at.isoformat()}",
            f"**Completed:** {report.completed_at.isoformat() if report.completed_at else 'In Progress'}",
            "",
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total | {report.summary.total} |",
            f"| Passed | {report.summary.passed} |",
            f"| Failed | {report.summary.failed} |",
            f"| Warnings | {report.summary.warned} |",
            f"| Pass Rate | {report.summary.pass_rate:.1f}% |",
            "",
        ]

        # Error categories
        if report.summary.error_categories:
            lines.extend([
                "## Error Categories",
                "",
                "| Category | Count |",
                "|----------|-------|",
            ])
            for cat, count in sorted(
                report.summary.error_categories.items(),
                key=lambda x: x[1],
                reverse=True,
            ):
                lines.append(f"| {cat} | {count} |")
            lines.append("")

        # Failed tests
        failed = [r for r in report.results if r.overall_result == TestResult.FAIL]
        if failed:
            lines.extend([
                "## Failed Tests",
                "",
            ])
            for result in failed:
                lines.extend([
                    f"### {result.question_id}",
                    f"- **Expected:** {result.expected_behavior.value}",
                    f"- **Actual:** {result.actual_behavior}",
                    f"- **Severity:** {result.severity.value if result.severity else 'N/A'}",
                    f"- **Category:** {result.error_category or 'N/A'}",
                ])
                if result.suggestions:
                    lines.append("- **Suggestions:**")
                    for s in result.suggestions:
                        lines.append(f"  - {s}")
                lines.append("")

        # Warnings
        warned = [r for r in report.results if r.overall_result == TestResult.WARN]
        if warned:
            lines.extend([
                "## Warnings",
                "",
            ])
            for result in warned:
                lines.extend([
                    f"### {result.question_id}",
                ])
                for w in result.warnings:
                    lines.append(f"- {w}")
                lines.append("")

        return "\n".join(lines)

    def _log_summary(self, report: TestRunReport) -> None:
        """Log summary to console."""
        s = report.summary
        logger.info("=" * 50)
        logger.info("TEST RUN SUMMARY")
        logger.info("=" * 50)
        logger.info(f"Total:    {s.total}")
        logger.info(f"Passed:   {s.passed}")
        logger.info(f"Failed:   {s.failed}")
        logger.info(f"Warnings: {s.warned}")
        logger.info(f"Pass Rate: {s.pass_rate:.1f}%")
        logger.info("=" * 50)

    def generate_patches(
        self,
        results: list[EvaluationResult],
    ) -> list[PatchSuggestion]:
        """
        Analyze failures and generate patch suggestions.

        Args:
            results: Evaluation results to analyze

        Returns:
            List of patch suggestions
        """
        # Group failures by error category
        failures_by_category: dict[str, list[EvaluationResult]] = {}
        for result in results:
            if result.overall_result == TestResult.FAIL and result.error_category:
                if result.error_category not in failures_by_category:
                    failures_by_category[result.error_category] = []
                failures_by_category[result.error_category].append(result)

        patches = []
        patch_id = 1

        for category, failures in failures_by_category.items():
            if len(failures) >= 2:  # Only patch patterns (2+ occurrences)
                patch = self._create_patch_for_category(
                    f"PATCH-{patch_id:03d}",
                    category,
                    failures,
                )
                if patch:
                    patches.append(patch)
                    patch_id += 1

        return patches

    def _create_patch_for_category(
        self,
        patch_id: str,
        category: str,
        failures: list[EvaluationResult],
    ) -> PatchSuggestion | None:
        """Create a patch suggestion for an error category."""
        affected_ids = [f.question_id for f in failures]

        if category == "type_mismatch":
            return PatchSuggestion(
                id=patch_id,
                title="Fix type mismatch in SQL generation",
                root_cause="LLM using wrong literal type for column",
                affected_questions=affected_ids,
                target_file="app/llm.py",
                patch_type="prompt_rule",
                patch_content="Add explicit type hints for commonly misused columns",
                location="## DATA TYPE RULES section",
                priority=Severity.HIGH,
                testing=f"Re-run {', '.join(affected_ids)}",
            )

        if category == "schema_error":
            return PatchSuggestion(
                id=patch_id,
                title="Fix schema reference errors",
                root_cause="LLM using non-existent tables or columns",
                affected_questions=affected_ids,
                target_file="app/llm.py",
                patch_type="prompt_rule",
                patch_content="Add explicit list of valid tables/columns",
                location="## CRITICAL section",
                priority=Severity.HIGH,
                testing=f"Re-run {', '.join(affected_ids)}",
            )

        if category == "safety_violation":
            return PatchSuggestion(
                id=patch_id,
                title="Strengthen safety validation",
                root_cause="SQL guard not catching all unsafe patterns",
                affected_questions=affected_ids,
                target_file="app/sql_guard.py",
                patch_type="validation_rule",
                patch_content="Add new validation check",
                location="validate_sql function",
                priority=Severity.CRITICAL,
                testing=f"Re-run {', '.join(affected_ids)} and test_sql_guard.py",
            )

        return None


def main() -> int:
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="SQL Testing Pipeline Orchestrator",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "quick", "failed-only"],
        default="full",
        help="Test mode: full (all), quick (first 10), failed-only (previous failures)",
    )
    parser.add_argument(
        "--question",
        "-q",
        type=str,
        help="Test a specific question by ID (e.g., Q042)",
    )
    parser.add_argument(
        "--category",
        "-c",
        type=str,
        help="Filter by category (e.g., aggregate, temporal)",
    )
    parser.add_argument(
        "--questions-file",
        type=Path,
        help="Path to questions JSON file",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--sample",
        "-s",
        type=int,
        help="Randomly sample N questions (reduces API calls)",
    )
    parser.add_argument(
        "--delay",
        "-d",
        type=float,
        default=2.0,
        help="Delay between API calls in seconds (default: 2.0)",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Initialize orchestrator
    orchestrator = SQLTestOrchestrator(
        questions_path=args.questions_file,
    )

    # Determine filters
    question_ids = [args.question] if args.question else None
    categories = None
    if args.category:
        try:
            categories = [Category(args.category)]
        except ValueError:
            logger.error(f"Unknown category: {args.category}")
            return 1

    # Load questions
    questions = orchestrator.load_questions()

    # Apply mode and sampling
    if args.mode == "quick" and not question_ids:
        # Quick mode: sample 10 diverse questions
        questions = questions[:10]
        logger.info("Quick mode: testing first 10 questions")
    elif args.sample and not question_ids:
        # Random sampling
        import random
        sample_size = min(args.sample, len(questions))
        questions = random.sample(questions, sample_size)
        logger.info(f"Sampled {sample_size} questions randomly")

    # Run pipeline with rate limiting
    try:
        report = orchestrator.run_pipeline(
            questions=questions,
            question_ids=question_ids,
            categories=categories,
            delay_seconds=args.delay,
        )

        # Generate patches for failures
        if report.summary.failed > 0:
            patches = orchestrator.generate_patches(report.results)
            if patches:
                logger.info(f"Generated {len(patches)} patch suggestions")
                for patch in patches:
                    logger.info(f"  - {patch.id}: {patch.title}")

        # Return exit code based on results
        if report.summary.failed > 0:
            return 1
        return 0

    except Exception as e:
        logger.exception(f"Pipeline failed: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
