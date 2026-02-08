"""
SQL Testing Pipeline.

A 4-agent testing pipeline for dry-run SQL validation:
1. Question Agent: Generates test questions
2. SQL Agent: Generates SQL from questions
3. Evaluator Agent: Validates SQL without database
4. Patcher Agent: Creates fixes for failures

Usage:
    uv run python -m tests.sql_testing.orchestrator --mode full
    uv run python -m tests.sql_testing.orchestrator --question Q042
"""

from tests.sql_testing.models import (
    TestCase,
    GenerationResult,
    EvaluationResult,
    LayerResult,
    PatchSuggestion,
    TestRunReport,
    ExpectedBehavior,
    Difficulty,
    Category,
    Severity,
)
from tests.sql_testing.evaluator import SQLEvaluator
from tests.sql_testing.orchestrator import SQLTestOrchestrator

__all__ = [
    "TestCase",
    "GenerationResult",
    "EvaluationResult",
    "LayerResult",
    "PatchSuggestion",
    "TestRunReport",
    "ExpectedBehavior",
    "Difficulty",
    "Category",
    "Severity",
    "SQLEvaluator",
    "SQLTestOrchestrator",
]
