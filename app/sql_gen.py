"""
SQL generation with schema context.

Uses the enhanced schema catalog (schema_knowledge.json) for:
- Rich column metadata with FK targets
- Join confidence scoring
- Thai medical context
- PHI detection
"""

from __future__ import annotations

from pathlib import Path

from app.schema_catalog import SchemaCatalog, get_schema_catalog, JoinStep
from app.concepts import ConceptLibrary, load_concepts
from app.config import get_settings
from app.llm import get_llm_client
from app.models import SQLGenerationResponse


# Priority tables to always include in context (most commonly queried)
PRIORITY_TABLES: list[str] = [
    # Core visit/admission tables
    "OVST",       # Outpatient visits
    "IPT",        # Inpatient admissions
    "PT",         # Patient master (PHI - for joins only)
    # Diagnosis tables
    "PTDIAG",     # Outpatient diagnoses
    "IPTSUMDIAG", # Inpatient diagnoses
    "ICD10",      # ICD-10 codes
    # Procedure tables
    "PTICD9CM",   # Outpatient procedures
    "IPTSUMOPRT", # Inpatient procedures
    "ICD9CM",     # ICD-9-CM codes
    # Prescription tables
    "PRSC",       # Prescription header
    "PRSCDT",     # Prescription details
    "MEDITEMDIS", # Drug master
    # Lab tables
    "LVST",       # Lab visit
    "LVSTEXM",    # Lab results
    "LABEXM",     # Lab exam master
    # Reference tables
    "CLINICLCT",  # Clinic locations
    "WARD",       # Ward master
    "DCT",        # Doctor master
    "PTTYPE",     # Patient type (insurance)
]


def build_schema_context(catalog: SchemaCatalog, max_tables: int = 60) -> str:
    """
    Build schema context string for LLM prompt.

    Args:
        catalog: Schema catalog with enhanced metadata
        max_tables: Maximum tables to include

    Returns:
        Formatted schema context string
    """
    lines = [
        "## DATABASE SCHEMA",
        "",
        "Use ONLY the tables and columns listed below. All table names must be prefixed with `KCMH_HIS.`",
        "(e.g., `KCMH_HIS.OVST`, `KCMH_HIS.PTDIAG`)",
        "",
        "### Universal Join Keys",
        "- `hn`: Hospital Number - links patient across all tables (PHI - never SELECT)",
        "- `an`: Admission Number - links inpatient episode tables",
        "- `vn`: Visit Number - links outpatient visit tables (OVST is home table)",
        "",
    ]

    # Collect tables to include
    tables_to_include: list[str] = []

    # Add priority tables first
    for t in PRIORITY_TABLES:
        if catalog.table_exists(t) and t not in tables_to_include:
            tables_to_include.append(t)

    # Add remaining tables up to max
    for t in sorted(catalog.tables.keys()):
        if t not in tables_to_include:
            tables_to_include.append(t)
        if len(tables_to_include) >= max_tables:
            break

    # Build table sections
    lines.append("### Tables and Columns")
    lines.append("")

    for table_name in tables_to_include:
        table = catalog.get_table(table_name)
        if not table:
            continue

        # Table header with Thai description
        comment = f" - {table.comment}" if table.comment else ""
        lines.append(f"**{table_name}**{comment}")

        # Columns with metadata
        col_parts = []
        for col_name, col in sorted(table.columns.items()):
            # Build column display
            markers = []
            if col.is_phi:
                markers.append("PHI")
            if col.is_pk:
                markers.append("PK")
            if col.is_fk and col.fk_targets:
                # Show FK target with confidence
                target = col.fk_targets[0]
                markers.append(f"FK->{target.table}")

            marker_str = f" [{','.join(markers)}]" if markers else ""

            # Add Thai comment if useful
            thai_hint = ""
            if col.comment and not col.is_phi:
                # Truncate long comments
                hint = col.comment[:30] + "..." if len(col.comment) > 30 else col.comment
                thai_hint = f" ({hint})"

            col_parts.append(f"{col_name}{marker_str}{thai_hint}")

        # Limit columns shown per table
        if len(col_parts) > 15:
            shown = col_parts[:12]
            shown.append(f"... +{len(col_parts) - 12} more columns")
            col_parts = shown

        lines.append(f"  Columns: {', '.join(col_parts)}")
        lines.append("")

    # Add join guidance
    lines.append("### Join Patterns (High Confidence)")
    lines.append("")
    lines.append("Use these join patterns. Confidence: high > medium > heuristic.")
    lines.append("")

    # Collect common high-confidence joins
    common_joins: list[tuple[str, str, str, str, str]] = []
    seen = set()

    for edge in catalog.schema.join_edges:
        if edge.confidence != "high":
            continue
        key = (edge.from_table, edge.to_table)
        if key in seen or (edge.to_table, edge.from_table) in seen:
            continue
        seen.add(key)
        common_joins.append((
            edge.from_table,
            edge.from_column,
            edge.to_table,
            edge.to_column,
            edge.rel_type,
        ))

    # Group by relationship type
    universal_joins = [j for j in common_joins if j[4] == "universal"][:10]
    table_match_joins = [j for j in common_joins if j[4] == "table match"][:15]

    if universal_joins:
        lines.append("**Universal key joins (always prefer these):**")
        for from_t, from_c, to_t, to_c, _ in universal_joins:
            lines.append(f"- {from_t}.{from_c} = {to_t}.{to_c}")
        lines.append("")

    if table_match_joins:
        lines.append("**Reference table joins:**")
        for from_t, from_c, to_t, to_c, _ in table_match_joins:
            lines.append(f"- {from_t}.{from_c} = {to_t}.{to_c}")
        lines.append("")

    # Add warnings section
    lines.append("### Important Warnings")
    lines.append("")
    lines.append("- **NEVER SELECT PHI columns** (hn, cid, names, addresses, phone, DOB)")
    lines.append("- **OVST.vn is the home key** for outpatient visits (not FK to IPT)")
    lines.append("- **IPT uses `an`** (admission number), not `vn`")
    lines.append("- **Always use date filters** on large tables (OVST, IPT, PRSC, etc.)")
    lines.append("- **Aggregate queries** don't need LIMIT; detail queries require LIMIT")
    lines.append("")

    # Add table hints
    lines.append("### Common Query Patterns")
    lines.append("")
    lines.append("**Count patients with condition X:**")
    lines.append("```sql")
    lines.append("SELECT COUNT(DISTINCT hn) FROM KCMH_HIS.PTDIAG WHERE icd10 LIKE 'E11%'")
    lines.append("```")
    lines.append("")
    lines.append("**OPD visits by clinic:**")
    lines.append("```sql")
    lines.append("SELECT c.cliniclctnm, COUNT(*) FROM KCMH_HIS.OVST o")
    lines.append("JOIN KCMH_HIS.CLINICLCT c ON o.cliniclct = c.cliniclct")
    lines.append("WHERE o.vstdate >= '2024-01-01' GROUP BY c.cliniclctnm")
    lines.append("```")

    return "\n".join(lines)


def build_join_context(
    catalog: SchemaCatalog,
    tables: list[str],
) -> str:
    """
    Build join recommendation context for specific tables.

    Args:
        catalog: Schema catalog
        tables: Tables the query will use

    Returns:
        Join recommendations for these tables
    """
    if len(tables) < 2:
        return ""

    rec = catalog.get_recommended_joins(tables)

    lines = ["## Recommended Joins for Your Query", ""]

    if rec.joins:
        for join in rec.joins:
            conf_marker = f"[{join.confidence}]"
            lines.append(
                f"- {join.from_table}.{join.from_column} = "
                f"{join.to_table}.{join.to_column} {conf_marker}"
            )

        if rec.warnings:
            lines.append("")
            lines.append("**Warnings:**")
            for w in rec.warnings:
                lines.append(f"- {w}")
    else:
        lines.append("No direct joins found. Consider intermediate tables.")

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
        concepts_path: Path | None = None,
    ) -> None:
        settings = get_settings()
        self._concepts_path = concepts_path or settings.concepts_path

        self._catalog: SchemaCatalog | None = None
        self._concepts: ConceptLibrary | None = None
        self._schema_context: str | None = None
        self._concepts_context: str | None = None

    @property
    def catalog(self) -> SchemaCatalog:
        """Get or load catalog."""
        if self._catalog is None:
            self._catalog = get_schema_catalog()
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

    def get_join_recommendation(self, tables: list[str]) -> str:
        """Get join recommendations for specific tables."""
        return build_join_context(self.catalog, tables)

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


def reset_sql_generator() -> None:
    """Reset the global generator instance."""
    global _generator
    _generator = None
