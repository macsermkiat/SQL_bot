"""Data models for Notion service tickets and evaluation results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class TicketData:
    """A single Notion service ticket with description and gold SQL."""

    id: str
    title: str
    notion_url: str
    ticket_number: str
    department: str
    status: str
    purpose: str
    data_level: list[str]
    created_at: str
    description_thai: str
    gold_sql: str
    has_phi_concern: bool
    gold_sql_dialect: Literal["oracle", "sqlserver", "postgresql"]

    @classmethod
    def from_dict(cls, d: dict) -> "TicketData":
        return cls(
            id=d["id"],
            title=d["title"],
            notion_url=d["notion_url"],
            ticket_number=d.get("ticket_number", ""),
            department=d.get("department", ""),
            status=d.get("status", ""),
            purpose=d.get("purpose", ""),
            data_level=d.get("data_level", []),
            created_at=d.get("created_at", ""),
            description_thai=d["description_thai"],
            gold_sql=d["gold_sql"],
            has_phi_concern=d.get("has_phi_concern", False),
            gold_sql_dialect=d.get("gold_sql_dialect", "oracle"),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "notion_url": self.notion_url,
            "ticket_number": self.ticket_number,
            "department": self.department,
            "status": self.status,
            "purpose": self.purpose,
            "data_level": self.data_level,
            "created_at": self.created_at,
            "description_thai": self.description_thai,
            "gold_sql": self.gold_sql,
            "has_phi_concern": self.has_phi_concern,
            "gold_sql_dialect": self.gold_sql_dialect,
        }

    def is_usable(self) -> bool:
        """Return True if ticket has both description and SQL."""
        return bool(self.description_thai.strip()) and bool(self.gold_sql.strip())


@dataclass
class SqlDiffResult:
    """Structural comparison between gold SQL and generated SQL."""

    ticket_id: str
    gold_tables: set[str]
    gen_tables: set[str]
    gold_joins: list[tuple[str, str]]
    gen_joins: list[tuple[str, str]]
    gold_filters: list[str]
    gen_filters: list[str]
    gold_aggregates: list[str]
    gen_aggregates: list[str]
    table_precision: float = 0.0
    table_recall: float = 0.0
    join_recall: float = 0.0
    filter_recall: float = 0.0
    aggregate_recall: float = 0.0
    overall_score: float = 0.0
    missing_tables: set[str] = field(default_factory=set)
    extra_tables: set[str] = field(default_factory=set)
    missing_joins: list[tuple[str, str]] = field(default_factory=list)
    missing_filters: list[str] = field(default_factory=list)
    parse_error: str | None = None


@dataclass
class EvalResult:
    """Full evaluation result for one ticket."""

    ticket: TicketData
    generated_sql: str | None
    generation_error: str | None
    diff: SqlDiffResult | None
    generation_time_ms: float = 0.0

    @property
    def is_success(self) -> bool:
        return self.generated_sql is not None and self.generation_error is None

    @property
    def score(self) -> float:
        if self.diff is None:
            return 0.0
        return self.diff.overall_score


@dataclass
class Learning:
    """A single extracted learning from comparing gold vs generated SQL."""

    ticket_id: str
    learning_type: Literal[
        "missing_table", "missing_join", "missing_filter",
        "wrong_icd_format", "missing_concept", "extra_table"
    ]
    detail: str
    suggested_fix: str
    target_file: Literal["concepts.yaml", "sql_corrections.yaml", "join_edges.csv"] | None = None
    confidence: float = 1.0


@dataclass
class PatchProposal:
    """A proposed patch to schema knowledge files."""

    patch_id: str
    title: str
    target_file: str
    patch_type: Literal["yaml_entry", "csv_row", "yaml_correction"]
    content: str
    affected_tickets: list[str]
    support_count: int
    applied: bool = False
