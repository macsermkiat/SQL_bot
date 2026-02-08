"""
Data models for SQL testing pipeline.

Defines test cases, results, and patch suggestions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal


class ExpectedBehavior(str, Enum):
    """Expected behavior for a test case."""

    VALID_SQL = "valid_sql"
    REJECT_PHI = "reject_phi"
    REJECT_UNSAFE = "reject_unsafe"
    NEEDS_CLARIFICATION = "needs_clarification"
    REJECT_SCHEMA = "reject_schema"
    REJECT_TYPE = "reject_type"


class Difficulty(str, Enum):
    """Test case difficulty level."""

    EASY = "easy"
    MODERATE = "moderate"
    HARD = "hard"


class Category(str, Enum):
    """Test case category."""

    AGGREGATE = "aggregate"
    MULTI_JOIN = "multi_join"
    TEMPORAL = "temporal"
    PHI_BOUNDARY = "phi_boundary"
    PHI_VIOLATION = "phi_violation"
    NEGATIVE = "negative"
    THAI = "thai"
    AMBIGUOUS = "ambiguous"
    EDGE_CASE = "edge_case"
    TYPE_MISMATCH = "type_mismatch"
    # Clinical complex categories
    DRUG_DISEASE = "drug_disease"
    DRUG_LAB = "drug_lab"
    DRUG_DISEASE_LAB = "drug_disease_lab"
    PROCEDURE_DIAGNOSIS = "procedure_diagnosis"
    PROCEDURE_MULTI_DIAGNOSIS = "procedure_multi_diagnosis"
    PROCEDURE_DIAGNOSIS_DEMOGRAPHIC = "procedure_diagnosis_demographic"
    PROCEDURE_DIAGNOSIS_LAB = "procedure_diagnosis_lab"
    PROCEDURE_CLASSIFICATION = "procedure_classification"
    PROCEDURE_DIAGNOSIS_COMPARISON = "procedure_diagnosis_comparison"
    PROCEDURE_DIAGNOSIS_STAGING = "procedure_diagnosis_staging"
    DRUG_LAB_ADVERSE = "drug_lab_adverse"
    DRUG_DISEASE_ADVERSE = "drug_disease_adverse"
    DRUG_DISEASE_LAB_TREND = "drug_disease_lab_trend"
    DRUG_DISEASE_LAB_IMPROVEMENT = "drug_disease_lab_improvement"
    DRUG_DISEASE_MULTI_LAB = "drug_disease_multi_lab"
    DRUG_LAB_RECURRENT = "drug_lab_recurrent"
    DRUG_LAB_MONITORING = "drug_lab_monitoring"
    DRUG_DISEASE_ADMISSION = "drug_disease_admission"
    DRUG_DISEASE_PROGRESSION = "drug_disease_progression"
    MULTI_DRUG_ADVERSE = "multi_drug_adverse"
    MULTI_DRUG_DISEASE_OUTCOME = "multi_drug_disease_outcome"
    DIAGNOSIS_PROCEDURE_LAB = "diagnosis_procedure_lab"


class Severity(str, Enum):
    """Failure severity level."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TestResult(str, Enum):
    """Overall test result."""

    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIP = "SKIP"


@dataclass
class TestCase:
    """A single test case for SQL validation."""

    id: str
    text: str
    text_thai: str | None = None
    difficulty: Difficulty = Difficulty.MODERATE
    category: Category = Category.AGGREGATE
    expected_behavior: ExpectedBehavior = ExpectedBehavior.VALID_SQL
    expected_tables: list[str] = field(default_factory=list)
    expected_concepts: list[str] = field(default_factory=list)
    negative_test: bool = False
    notes: str | None = None
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestCase:
        """Create TestCase from dictionary."""
        return cls(
            id=data["id"],
            text=data["text"],
            text_thai=data.get("text_thai"),
            difficulty=Difficulty(data.get("difficulty", "moderate")),
            category=Category(data.get("category", "aggregate")),
            expected_behavior=ExpectedBehavior(
                data.get("expected_behavior", "valid_sql")
            ),
            expected_tables=data.get("expected_tables", []),
            expected_concepts=data.get("expected_concepts", []),
            negative_test=data.get("negative_test", False),
            notes=data.get("notes"),
            tags=data.get("tags", []),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "text": self.text,
            "text_thai": self.text_thai,
            "difficulty": self.difficulty.value,
            "category": self.category.value,
            "expected_behavior": self.expected_behavior.value,
            "expected_tables": self.expected_tables,
            "expected_concepts": self.expected_concepts,
            "negative_test": self.negative_test,
            "notes": self.notes,
            "tags": self.tags,
        }


@dataclass
class SQLGenerationOutput:
    """Output from SQL generation (mirrors SQLGenerationResponse)."""

    sql: str = ""
    needs_clarification: bool = False
    clarification_question: str | None = None
    clarified_question: str = ""
    assumptions: list[str] = field(default_factory=list)
    concepts_used: list[str] = field(default_factory=list)
    validation_checks: list[str] = field(default_factory=list)
    answer_plan: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SQLGenerationOutput:
        """Create from dictionary."""
        return cls(
            sql=data.get("sql", ""),
            needs_clarification=data.get("needs_clarification", False),
            clarification_question=data.get("clarification_question"),
            clarified_question=data.get("clarified_question", ""),
            assumptions=data.get("assumptions", []),
            concepts_used=data.get("concepts_used", []),
            validation_checks=data.get("validation_checks", []),
            answer_plan=data.get("answer_plan", ""),
            confidence=data.get("confidence", "medium"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "sql": self.sql,
            "needs_clarification": self.needs_clarification,
            "clarification_question": self.clarification_question,
            "clarified_question": self.clarified_question,
            "assumptions": self.assumptions,
            "concepts_used": self.concepts_used,
            "validation_checks": self.validation_checks,
            "answer_plan": self.answer_plan,
            "confidence": self.confidence,
        }


@dataclass
class GenerationResult:
    """Result of SQL generation for a test case."""

    question_id: str
    question_text: str
    generation_success: bool
    response: SQLGenerationOutput | None = None
    error: str | None = None
    generation_time_ms: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GenerationResult:
        """Create from dictionary."""
        response = None
        if data.get("response"):
            response = SQLGenerationOutput.from_dict(data["response"])
        return cls(
            question_id=data["question_id"],
            question_text=data["question_text"],
            generation_success=data["generation_success"],
            response=response,
            error=data.get("error"),
            generation_time_ms=data.get("generation_time_ms", 0.0),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "question_id": self.question_id,
            "question_text": self.question_text,
            "generation_success": self.generation_success,
            "response": self.response.to_dict() if self.response else None,
            "error": self.error,
            "generation_time_ms": self.generation_time_ms,
        }


@dataclass
class LayerResult:
    """Result of a single validation layer."""

    passed: bool
    details: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "passed": self.passed,
            "details": self.details,
            "warnings": self.warnings,
        }


@dataclass
class EvaluationResult:
    """Result of SQL evaluation."""

    question_id: str
    overall_result: TestResult = TestResult.PASS
    layers: dict[str, LayerResult] = field(default_factory=dict)
    expected_behavior: ExpectedBehavior = ExpectedBehavior.VALID_SQL
    actual_behavior: str = ""
    behavior_match: bool = False
    tables_used: list[str] = field(default_factory=list)
    tables_expected: list[str] = field(default_factory=list)
    tables_match: bool = False
    concepts_used: list[str] = field(default_factory=list)
    concepts_expected: list[str] = field(default_factory=list)
    concepts_match: bool = False
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    severity: Severity | None = None
    error_category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "question_id": self.question_id,
            "overall_result": self.overall_result.value,
            "layers": {k: v.to_dict() for k, v in self.layers.items()},
            "expected_behavior": self.expected_behavior.value,
            "actual_behavior": self.actual_behavior,
            "behavior_match": self.behavior_match,
            "tables_used": self.tables_used,
            "tables_expected": self.tables_expected,
            "tables_match": self.tables_match,
            "concepts_used": self.concepts_used,
            "concepts_expected": self.concepts_expected,
            "concepts_match": self.concepts_match,
            "warnings": self.warnings,
            "suggestions": self.suggestions,
            "severity": self.severity.value if self.severity else None,
            "error_category": self.error_category,
        }


@dataclass
class PatchSuggestion:
    """A suggested patch for fixing test failures."""

    id: str
    title: str
    root_cause: str
    affected_questions: list[str] = field(default_factory=list)
    target_file: str = ""
    patch_type: str = ""  # prompt_rule, validation_rule, concept_fix
    patch_content: str = ""
    location: str = ""
    priority: Severity = Severity.MEDIUM
    testing: str = ""
    applied: bool = False
    applied_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "root_cause": self.root_cause,
            "affected_questions": self.affected_questions,
            "target_file": self.target_file,
            "patch_type": self.patch_type,
            "patch_content": self.patch_content,
            "location": self.location,
            "priority": self.priority.value,
            "testing": self.testing,
            "applied": self.applied,
            "applied_at": self.applied_at.isoformat() if self.applied_at else None,
        }


@dataclass
class TestRunSummary:
    """Summary statistics for a test run."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    warned: int = 0
    skipped: int = 0
    pass_rate: float = 0.0
    by_category: dict[str, dict[str, int]] = field(default_factory=dict)
    by_severity: dict[str, int] = field(default_factory=dict)
    error_categories: dict[str, int] = field(default_factory=dict)

    def calculate_pass_rate(self) -> None:
        """Calculate pass rate from totals."""
        if self.total > 0:
            self.pass_rate = (self.passed / self.total) * 100

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "warned": self.warned,
            "skipped": self.skipped,
            "pass_rate": round(self.pass_rate, 2),
            "by_category": self.by_category,
            "by_severity": self.by_severity,
            "error_categories": self.error_categories,
        }


@dataclass
class TestRunReport:
    """Complete report for a test run."""

    run_id: str
    started_at: datetime
    completed_at: datetime | None = None
    summary: TestRunSummary = field(default_factory=TestRunSummary)
    results: list[EvaluationResult] = field(default_factory=list)
    patches: list[PatchSuggestion] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "summary": self.summary.to_dict(),
            "results": [r.to_dict() for r in self.results],
            "patches": [p.to_dict() for p in self.patches],
            "recommendations": self.recommendations,
        }


@dataclass
class QuestionGenerationRequest:
    """Request for generating test questions."""

    count: int = 10
    categories: list[Category] | None = None
    difficulty_weights: dict[str, float] | None = None
    include_negative: bool = True
    include_thai: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "count": self.count,
            "categories": [c.value for c in self.categories] if self.categories else None,
            "difficulty_weights": self.difficulty_weights,
            "include_negative": self.include_negative,
            "include_thai": self.include_thai,
        }
