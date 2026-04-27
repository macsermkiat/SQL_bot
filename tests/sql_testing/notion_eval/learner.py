"""Extract learnings from SQL diff results to drive schema knowledge updates."""

from __future__ import annotations

import logging
import re

from tests.sql_testing.notion_eval.ticket_models import (
    EvalResult,
    Learning,
    SqlDiffResult,
    TicketData,
)

logger = logging.getLogger(__name__)

_ICD_DOTTED = re.compile(r"\b([A-Z]\d{2})\.\d+\b")
_ICD_NUMERIC_DOTTED = re.compile(r"'\d{2,3}\.\d+'")


def _detect_icd_format_issue(gold_sql: str, gen_sql: str) -> bool:
    """Return True if gen SQL uses dotted ICD codes while gold does not."""
    gold_has_dots = bool(_ICD_DOTTED.search(gold_sql) or _ICD_NUMERIC_DOTTED.search(gold_sql))
    gen_has_dots = bool(_ICD_DOTTED.search(gen_sql) or _ICD_NUMERIC_DOTTED.search(gen_sql))
    return gen_has_dots and not gold_has_dots


def extract_learnings(result: EvalResult) -> list[Learning]:
    """Derive a list of Learning items from one evaluation result."""
    if not result.is_success or result.diff is None:
        return []

    diff: SqlDiffResult = result.diff
    ticket: TicketData = result.ticket
    learnings: list[Learning] = []

    for table in sorted(diff.missing_tables):
        learnings.append(
            Learning(
                ticket_id=ticket.id,
                learning_type="missing_table",
                detail=f"Gold table '{table}' absent from generated SQL",
                suggested_fix=(
                    f"Add or check concept mapping that resolves to table '{table}'. "
                    f"Verify join_edges.csv has entry for '{table}'."
                ),
                target_file="concepts.yaml",
                confidence=1.0,
            )
        )

    for table in sorted(diff.extra_tables):
        learnings.append(
            Learning(
                ticket_id=ticket.id,
                learning_type="extra_table",
                detail=f"Generated SQL includes extra table '{table}' not in gold",
                suggested_fix=(
                    f"Check if concept for this question incorrectly maps to '{table}'. "
                    "Add negative example to sql_corrections.yaml if recurring."
                ),
                target_file="sql_corrections.yaml",
                confidence=0.8,
            )
        )

    for left, right in diff.missing_joins:
        learnings.append(
            Learning(
                ticket_id=ticket.id,
                learning_type="missing_join",
                detail=f"Gold join '{left} = {right}' missing from generated SQL",
                suggested_fix=(
                    f"Add join edge between '{left}' and '{right}' in join_edges.csv "
                    "with confidence=high."
                ),
                target_file="join_edges.csv",
                confidence=1.0,
            )
        )

    for filt in diff.missing_filters:
        learnings.append(
            Learning(
                ticket_id=ticket.id,
                learning_type="missing_filter",
                detail=f"Gold filter predicate missing: {filt[:120]}",
                suggested_fix=(
                    "Add a correction pattern in sql_corrections.yaml that enforces "
                    "this filter condition for similar question types."
                ),
                target_file="sql_corrections.yaml",
                confidence=0.9,
            )
        )

    if result.generated_sql and _detect_icd_format_issue(ticket.gold_sql, result.generated_sql):
        learnings.append(
            Learning(
                ticket_id=ticket.id,
                learning_type="wrong_icd_format",
                detail="Generated SQL uses dotted ICD codes (e.g. 'J18.0') but DB stores without dots",
                suggested_fix=(
                    "Add ICD code format reminder to concepts.yaml: "
                    "ICD codes stored WITHOUT dots — use LIKE 'J18%' not LIKE 'J18.0%'."
                ),
                target_file="concepts.yaml",
                confidence=1.0,
            )
        )

    if diff.missing_tables and not diff.missing_joins:
        for table in sorted(diff.missing_tables):
            learnings.append(
                Learning(
                    ticket_id=ticket.id,
                    learning_type="missing_concept",
                    detail=(
                        f"Table '{table}' needed but no concept maps to it "
                        f"for question: {ticket.description_thai[:80]}"
                    ),
                    suggested_fix=(
                        f"Add new concept entry in concepts.yaml that maps relevant "
                        f"Thai clinical terms to table '{table}'."
                    ),
                    target_file="concepts.yaml",
                    confidence=0.9,
                )
            )

    logger.debug(
        "Ticket %s: %d learning(s) extracted (score=%.2f)",
        ticket.ticket_number or ticket.id[:8],
        len(learnings),
        result.score,
    )
    return learnings
