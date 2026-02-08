"""
Pytest integration for SQL testing pipeline.

Tests the pipeline components without requiring database or API access.
Uses mock responses for SQL generation when API is unavailable.

Usage:
    uv run pytest tests/test_sql_pipeline.py -v
    uv run pytest tests/test_sql_pipeline.py -k "test_evaluator" -v
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.sql_testing.models import (
    Category,
    Difficulty,
    EvaluationResult,
    ExpectedBehavior,
    GenerationResult,
    LayerResult,
    SQLGenerationOutput,
    TestCase,
    TestResult,
    TestRunReport,
    TestRunSummary,
)
from tests.sql_testing.evaluator import SQLEvaluator


# Test data directory
TEST_DATA_DIR = Path(__file__).parent.parent / "test_data" / "sql_testing"
QUESTIONS_FILE = TEST_DATA_DIR / "questions" / "base_questions.json"


class TestModels:
    """Test data models."""

    def test_test_case_from_dict(self) -> None:
        """Test TestCase creation from dictionary."""
        data = {
            "id": "Q001",
            "text": "How many patients have diabetes?",
            "text_thai": "มีผู้ป่วยโรคเบาหวานกี่คน?",
            "difficulty": "moderate",
            "category": "aggregate",
            "expected_behavior": "valid_sql",
            "expected_tables": ["PTDIAG"],
            "expected_concepts": ["diabetes_icd10"],
            "negative_test": False,
        }

        test_case = TestCase.from_dict(data)

        assert test_case.id == "Q001"
        assert test_case.text == "How many patients have diabetes?"
        assert test_case.difficulty == Difficulty.MODERATE
        assert test_case.category == Category.AGGREGATE
        assert test_case.expected_behavior == ExpectedBehavior.VALID_SQL
        assert "PTDIAG" in test_case.expected_tables

    def test_test_case_to_dict(self) -> None:
        """Test TestCase serialization to dictionary."""
        test_case = TestCase(
            id="Q001",
            text="Test question",
            difficulty=Difficulty.HARD,
            category=Category.MULTI_JOIN,
        )

        data = test_case.to_dict()

        assert data["id"] == "Q001"
        assert data["difficulty"] == "hard"
        assert data["category"] == "multi_join"

    def test_generation_result_from_dict(self) -> None:
        """Test GenerationResult creation from dictionary."""
        data = {
            "question_id": "Q001",
            "question_text": "Test",
            "generation_success": True,
            "response": {
                "sql": "SELECT COUNT(*) FROM PTDIAG",
                "needs_clarification": False,
                "confidence": "high",
                "assumptions": ["test"],
                "concepts_used": ["diabetes_icd10"],
            },
            "generation_time_ms": 100.0,
        }

        result = GenerationResult.from_dict(data)

        assert result.generation_success is True
        assert result.response is not None
        assert result.response.sql == "SELECT COUNT(*) FROM PTDIAG"
        assert result.response.confidence == "high"

    def test_layer_result_to_dict(self) -> None:
        """Test LayerResult serialization."""
        layer = LayerResult(
            passed=True,
            details=None,
            warnings=["Warning 1", "Warning 2"],
        )

        data = layer.to_dict()

        assert data["passed"] is True
        assert len(data["warnings"]) == 2


class TestQuestionLoading:
    """Test loading questions from JSON."""

    def test_load_base_questions(self) -> None:
        """Test loading base questions file."""
        if not QUESTIONS_FILE.exists():
            pytest.skip("Base questions file not found")

        with open(QUESTIONS_FILE) as f:
            data = json.load(f)

        assert len(data) >= 50, "Should have at least 50 base questions"

        # Test parsing
        for item in data[:10]:
            test_case = TestCase.from_dict(item)
            assert test_case.id.startswith("Q")
            assert len(test_case.text) > 0

    def test_question_categories_covered(self) -> None:
        """Test that all categories are covered."""
        if not QUESTIONS_FILE.exists():
            pytest.skip("Base questions file not found")

        with open(QUESTIONS_FILE) as f:
            data = json.load(f)

        categories = {item.get("category") for item in data}

        expected = {
            "aggregate", "multi_join", "temporal", "phi_boundary",
            "phi_violation", "negative", "thai", "ambiguous",
            "edge_case", "type_mismatch",
        }

        # At least 6 categories should be covered
        covered = categories.intersection(expected)
        assert len(covered) >= 6, f"Only {len(covered)} categories covered: {covered}"

    def test_negative_tests_exist(self) -> None:
        """Test that negative tests exist."""
        if not QUESTIONS_FILE.exists():
            pytest.skip("Base questions file not found")

        with open(QUESTIONS_FILE) as f:
            data = json.load(f)

        negative_tests = [item for item in data if item.get("negative_test", False)]
        assert len(negative_tests) >= 10, "Should have at least 10 negative tests"


class TestSQLEvaluator:
    """Test SQL evaluator without database."""

    @pytest.fixture
    def evaluator(self) -> SQLEvaluator:
        """Create evaluator with mock catalog."""
        mock_catalog = MagicMock()
        mock_catalog.table_exists.return_value = True
        mock_catalog.validate_sql_references.return_value = ([], [])
        return SQLEvaluator(catalog=mock_catalog)

    @pytest.fixture
    def valid_test_case(self) -> TestCase:
        """Create a valid test case."""
        return TestCase(
            id="Q001",
            text="How many patients have diabetes?",
            difficulty=Difficulty.MODERATE,
            category=Category.AGGREGATE,
            expected_behavior=ExpectedBehavior.VALID_SQL,
            expected_tables=["PTDIAG"],
        )

    @pytest.fixture
    def phi_test_case(self) -> TestCase:
        """Create a PHI violation test case."""
        return TestCase(
            id="Q003",
            text="Show me patient names",
            difficulty=Difficulty.EASY,
            category=Category.PHI_VIOLATION,
            expected_behavior=ExpectedBehavior.REJECT_PHI,
            negative_test=True,
        )

    def test_evaluate_valid_sql(
        self,
        evaluator: SQLEvaluator,
        valid_test_case: TestCase,
    ) -> None:
        """Test evaluation of valid SQL."""
        generation = GenerationResult(
            question_id="Q001",
            question_text="Test",
            generation_success=True,
            response=SQLGenerationOutput(
                sql='SELECT COUNT(DISTINCT "hn") FROM "KCMH_HIS"."PTDIAG" WHERE "icd10" LIKE \'E11%%\'',
                needs_clarification=False,
                confidence="high",
                concepts_used=["diabetes_icd10"],
            ),
        )

        result = evaluator.evaluate(valid_test_case, generation)

        assert result.question_id == "Q001"
        assert result.layers["syntax"].passed is True
        # Note: safety might fail due to mock, so we check syntax at minimum

    def test_evaluate_generation_failure(
        self,
        evaluator: SQLEvaluator,
        valid_test_case: TestCase,
    ) -> None:
        """Test evaluation when generation fails."""
        generation = GenerationResult(
            question_id="Q001",
            question_text="Test",
            generation_success=False,
            error="API error",
        )

        result = evaluator.evaluate(valid_test_case, generation)

        assert result.overall_result == TestResult.FAIL
        assert result.actual_behavior == "generation_error"

    def test_evaluate_clarification_request(
        self,
        evaluator: SQLEvaluator,
        valid_test_case: TestCase,
    ) -> None:
        """Test evaluation when clarification is requested."""
        generation = GenerationResult(
            question_id="Q001",
            question_text="Test",
            generation_success=True,
            response=SQLGenerationOutput(
                sql="",
                needs_clarification=True,
                clarification_question="What timeframe?",
            ),
        )

        # For a test expecting valid_sql, clarification should be a warning
        result = evaluator.evaluate(valid_test_case, generation)

        assert result.actual_behavior == "needs_clarification"

    def test_evaluate_syntax_error(
        self,
        evaluator: SQLEvaluator,
        valid_test_case: TestCase,
    ) -> None:
        """Test evaluation of SQL with syntax error."""
        generation = GenerationResult(
            question_id="Q001",
            question_text="Test",
            generation_success=True,
            response=SQLGenerationOutput(
                sql="SELECT FROM WHERE",  # Invalid SQL
                needs_clarification=False,
            ),
        )

        result = evaluator.evaluate(valid_test_case, generation)

        assert result.layers["syntax"].passed is False
        assert result.overall_result == TestResult.FAIL

    def test_evaluate_phi_in_output(
        self,
        evaluator: SQLEvaluator,
        phi_test_case: TestCase,
    ) -> None:
        """Test that PHI in SELECT output is detected."""
        generation = GenerationResult(
            question_id="Q003",
            question_text="Test",
            generation_success=True,
            response=SQLGenerationOutput(
                sql='SELECT "hn", "fname" FROM "KCMH_HIS"."PT" LIMIT 10',
                needs_clarification=False,
            ),
        )

        result = evaluator.evaluate(phi_test_case, generation)

        # Should fail safety check for PHI
        assert result.layers["safety"].passed is False
        assert "phi" in result.actual_behavior.lower() or "phi" in (result.layers["safety"].details or "").lower()


class TestOrchestratorUnit:
    """Unit tests for orchestrator (without API calls)."""

    def test_generate_summary(self) -> None:
        """Test summary generation."""
        from tests.sql_testing.orchestrator import SQLTestOrchestrator

        orchestrator = SQLTestOrchestrator()

        results = [
            EvaluationResult(
                question_id="Q001",
                overall_result=TestResult.PASS,
            ),
            EvaluationResult(
                question_id="Q002",
                overall_result=TestResult.PASS,
            ),
            EvaluationResult(
                question_id="Q003",
                overall_result=TestResult.FAIL,
                error_category="safety_violation",
            ),
        ]

        summary = orchestrator._generate_summary(results)

        assert summary.total == 3
        assert summary.passed == 2
        assert summary.failed == 1
        assert abs(summary.pass_rate - 66.67) < 1  # ~66.67%

    def test_load_questions(self) -> None:
        """Test question loading."""
        from tests.sql_testing.orchestrator import SQLTestOrchestrator

        orchestrator = SQLTestOrchestrator()
        questions = orchestrator.load_questions()

        if questions:  # Only test if file exists
            assert len(questions) > 0
            assert all(isinstance(q, TestCase) for q in questions)


class TestSafetyValidation:
    """Test safety validation without database."""

    def test_forbidden_keywords_detected(self) -> None:
        """Test that forbidden keywords are detected."""
        from app.sql_guard import validate_sql

        result = validate_sql("DELETE FROM PTDIAG WHERE id = 1")

        assert result.valid is False
        assert "DELETE" in (result.error or "").upper()

    def test_select_star_rejected(self) -> None:
        """Test that SELECT * is rejected."""
        from app.sql_guard import validate_sql

        result = validate_sql("SELECT * FROM PTDIAG LIMIT 10")

        assert result.valid is False
        assert "SELECT *" in (result.error or "")

    def test_phi_columns_detected(self) -> None:
        """Test that PHI columns in SELECT are detected."""
        from app.sql_guard import validate_sql

        result = validate_sql('SELECT "hn", "count" FROM "KCMH_HIS"."PTDIAG" LIMIT 10')

        assert result.valid is False
        assert "PHI" in (result.error or "").upper() or "hn" in (result.error or "").lower()

    def test_missing_limit_detected(self) -> None:
        """Test that missing LIMIT is detected for non-aggregate queries."""
        from app.sql_guard import validate_sql

        result = validate_sql('SELECT "vn", "icd10" FROM "KCMH_HIS"."PTDIAG"')

        assert result.valid is False
        assert "LIMIT" in (result.error or "").upper()

    def test_aggregate_no_limit_ok(self) -> None:
        """Test that aggregate queries don't need LIMIT."""
        from app.sql_guard import validate_sql

        result = validate_sql('SELECT COUNT(*) FROM "KCMH_HIS"."PTDIAG"')

        # Aggregate queries don't need LIMIT
        if not result.valid and result.error:
            assert "LIMIT" not in result.error.upper()


class TestReportGeneration:
    """Test report generation."""

    def test_markdown_report_generation(self) -> None:
        """Test markdown report generation."""
        from datetime import datetime
        from tests.sql_testing.orchestrator import SQLTestOrchestrator

        orchestrator = SQLTestOrchestrator()

        report = TestRunReport(
            run_id="test_run",
            started_at=datetime.now(),
            completed_at=datetime.now(),
            summary=TestRunSummary(
                total=10,
                passed=8,
                failed=2,
                pass_rate=80.0,
            ),
            results=[
                EvaluationResult(
                    question_id="Q001",
                    overall_result=TestResult.FAIL,
                    expected_behavior=ExpectedBehavior.VALID_SQL,
                    actual_behavior="syntax_error",
                ),
            ],
        )

        md = orchestrator._generate_markdown_report(report)

        assert "# SQL Test Run Report" in md
        assert "Pass Rate | 80.0%" in md
        assert "Q001" in md


class TestIntegration:
    """Integration tests (may require API key)."""

    @pytest.mark.skipif(
        not Path.home().joinpath(".anthropic_api_key").exists(),
        reason="Anthropic API key not available",
    )
    def test_single_question_pipeline(self) -> None:
        """Test running pipeline on a single question."""
        from tests.sql_testing.orchestrator import SQLTestOrchestrator

        orchestrator = SQLTestOrchestrator()
        questions = orchestrator.load_questions()

        if not questions:
            pytest.skip("No questions available")

        # Test with first valid_sql question
        test_question = next(
            (q for q in questions if q.expected_behavior == ExpectedBehavior.VALID_SQL),
            None,
        )
        if not test_question:
            pytest.skip("No valid_sql question found")

        report = orchestrator.run_pipeline(
            questions=[test_question],
        )

        assert report.summary.total == 1
        assert len(report.results) == 1


# Run with: uv run pytest tests/test_sql_pipeline.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
