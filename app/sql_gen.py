"""
SQL generation with schema context.
"""

from __future__ import annotations

from pathlib import Path

from app.catalog import Catalog, load_catalog
from app.concepts import ConceptLibrary, load_concepts
from app.config import get_settings
from app.llm import get_llm_client
from app.models import SQLGenerationResponse


def build_schema_context(catalog: Catalog, max_tables: int = 50) -> str:
    """
    Build schema context string for LLM prompt.

    Args:
        catalog: Parsed schema catalog
        max_tables: Maximum tables to include

    Returns:
        Formatted schema context string
    """
    lines = [
        "## VERIFIED TABLES AND COLUMNS",
        "",
        "**IMPORTANT**: Only use tables and columns listed below. The schema is incomplete,",
        "so if a column isn't listed, it may not exist or may have a different name.",
        ""
    ]

    # Sort tables by name for consistency
    table_names = sorted(catalog.tables.keys())[:max_tables]

    for table_name in table_names:
        table = catalog.tables[table_name]
        col_names = list(table.columns.keys())

        if not col_names:
            lines.append(f"**{table_name}**: (no verified columns)")
            continue

        # Mark PHI columns
        col_display = []
        for col in col_names:
            if table.columns[col].is_phi:
                col_display.append(f"{col} [PHI-DO NOT SELECT]")
            elif table.columns[col].is_pk:
                col_display.append(f"{col} [PK]")
            elif table.columns[col].is_fk:
                col_display.append(f"{col} [FK]")
            else:
                col_display.append(col)

        extra = ""
        if table.additional_columns > 0:
            extra = f" (+{table.additional_columns} unverified columns)"

        lines.append(f"**{table_name}**: {', '.join(col_display)}{extra}")

    # Add relationship hints
    if catalog.relationships:
        lines.append("\n## Key Relationships\n")
        # Group by confidence
        high_conf = [r for r in catalog.relationships if r.confidence == "high"][:20]
        for rel in high_conf:
            lines.append(f"- {rel.from_table} -> {rel.to_table} via {rel.join_key}")

    # Add common table mapping hints
    lines.append("\n## Table Name Hints")
    lines.append("- Patient diagnoses: PTDIAG (outpatient), IPTSUMDIAG (inpatient)")
    lines.append("- Outpatient visits: OVST")
    lines.append("- Inpatient admissions: IPT")
    lines.append("- Prescriptions: PRSC, PRSCDT")
    lines.append("- Patient info: PT")

    return "\n".join(lines)


def build_concepts_context(concepts: ConceptLibrary) -> str:
    """
    Build concepts context string for LLM prompt.

    Args:
        concepts: Loaded concept library

    Returns:
        Formatted concepts context string
    """
    if not concepts.concepts:
        return "No clinical concepts defined yet."

    lines = ["## Clinical Concept Definitions\n"]

    for name, concept in concepts.concepts.items():
        lines.append(f"**{name}**: {concept.description}")
        if concept.condition:
            lines.append(f"  - SQL condition: `{concept.condition}`")
        if concept.tests:
            lines.append(f"  - Tests: {', '.join(concept.tests)}")
        if concept.icd10_codes:
            lines.append(f"  - ICD-10: {', '.join(concept.icd10_codes)}")
        lines.append("")

    return "\n".join(lines)


class SQLGenerator:
    """SQL generator with schema and concept grounding."""

    def __init__(
        self,
        catalog_path: Path | None = None,
        concepts_path: Path | None = None,
    ) -> None:
        settings = get_settings()
        self._catalog_path = catalog_path or settings.catalog_path
        self._concepts_path = concepts_path or settings.concepts_path

        self._catalog: Catalog | None = None
        self._concepts: ConceptLibrary | None = None
        self._schema_context: str | None = None
        self._concepts_context: str | None = None

    @property
    def catalog(self) -> Catalog:
        """Get or load catalog."""
        if self._catalog is None:
            self._catalog = load_catalog(self._catalog_path)
        return self._catalog

    @property
    def concepts(self) -> ConceptLibrary:
        """Get or load concepts."""
        if self._concepts is None:
            self._concepts = load_concepts(self._concepts_path)
        return self._concepts

    @property
    def schema_context(self) -> str:
        """Get or build schema context."""
        if self._schema_context is None:
            self._schema_context = build_schema_context(self.catalog)
        return self._schema_context

    @property
    def concepts_context(self) -> str:
        """Get or build concepts context."""
        if self._concepts_context is None:
            self._concepts_context = build_concepts_context(self.concepts)
        return self._concepts_context

    def generate(
        self,
        question: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> SQLGenerationResponse:
        """
        Generate SQL from natural language question.

        Args:
            question: User's analytical question
            conversation_history: Previous conversation for context

        Returns:
            SQLGenerationResponse with SQL and metadata
        """
        client = get_llm_client()
        return client.generate_sql(
            user_question=question,
            schema_context=self.schema_context,
            concepts_context=self.concepts_context,
            conversation_history=conversation_history,
        )

    def reload(self) -> None:
        """Reload catalog and concepts from disk."""
        self._catalog = None
        self._concepts = None
        self._schema_context = None
        self._concepts_context = None


# Global generator instance
_generator: SQLGenerator | None = None


def get_sql_generator() -> SQLGenerator:
    """Get global SQL generator instance."""
    global _generator
    if _generator is None:
        _generator = SQLGenerator()
    return _generator
