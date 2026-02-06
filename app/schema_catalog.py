"""
Schema Catalog - Enhanced schema access with join path finding.

Provides:
- Join path discovery between tables (BFS)
- Optimal join strategy recommendations
- Join validation with confidence and warnings
- Backward-compatible interface with old catalog.py

Uses schema_knowledge.json from schema_parser.py.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.schema_parser import (
    SchemaKnowledge,
    JoinEdge,
    FKTarget,
    Column,
    Table,
    get_schema_knowledge,
    load_schema_knowledge,
    PHI_COLUMNS,
    UNIVERSAL_KEYS,
)


ConfidenceLevel = Literal["high", "medium", "heuristic"]

# Confidence scoring for join prioritization
CONFIDENCE_SCORES: dict[str, int] = {
    "high": 100,
    "medium": 50,
    "heuristic": 25,
}

# Relationship type bonuses
REL_TYPE_BONUSES: dict[str, int] = {
    "universal": 50,      # hn, an, vn - highest priority
    "table match": 30,    # column name = table name
    "within_family": 10,  # Same family tables
    "heuristic_home": -20,  # Suspicious, might be home key
}


@dataclass
class JoinStep:
    """Single step in a join path."""
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    confidence: ConfidenceLevel
    rel_type: str
    score: int
    warning: str = ""


@dataclass
class JoinPath:
    """Complete join path between two tables."""
    from_table: str
    to_table: str
    steps: list[JoinStep]
    total_score: int
    warnings: list[str] = field(default_factory=list)

    @property
    def hop_count(self) -> int:
        return len(self.steps)

    @property
    def is_direct(self) -> bool:
        return self.hop_count == 1


@dataclass
class JoinRecommendation:
    """Recommended join strategy for multiple tables."""
    tables: list[str]
    joins: list[JoinStep]
    total_score: int
    warnings: list[str] = field(default_factory=list)

    def to_sql_joins(self, base_table: str | None = None) -> str:
        """Generate SQL JOIN clauses."""
        if not self.joins:
            return ""

        lines = []
        joined_tables = {base_table or self.joins[0].from_table}

        for step in self.joins:
            # Determine which table to join
            if step.from_table in joined_tables and step.to_table not in joined_tables:
                join_table = step.to_table
                on_clause = f"{step.from_table}.{step.from_column} = {step.to_table}.{step.to_column}"
                joined_tables.add(step.to_table)
            elif step.to_table in joined_tables and step.from_table not in joined_tables:
                join_table = step.from_table
                on_clause = f"{step.from_table}.{step.from_column} = {step.to_table}.{step.to_column}"
                joined_tables.add(step.from_table)
            else:
                # Both already joined or neither - skip
                continue

            lines.append(f"JOIN {join_table} ON {on_clause}")

        return "\n".join(lines)


@dataclass
class JoinValidation:
    """Result of join validation."""
    valid: bool
    confidence: ConfidenceLevel
    score: int
    warnings: list[str] = field(default_factory=list)
    suggestion: str = ""


class SchemaCatalog:
    """
    Enhanced schema catalog with join intelligence.

    Features:
    - Join path finding using BFS
    - Confidence-based join scoring
    - Join validation with warnings
    - PHI column detection
    - Backward-compatible with old Catalog interface
    """

    def __init__(self, schema: SchemaKnowledge | None = None) -> None:
        self._schema = schema

    @property
    def schema(self) -> SchemaKnowledge:
        """Get or load schema knowledge."""
        if self._schema is None:
            self._schema = get_schema_knowledge()
        return self._schema

    # ==================== Basic Accessors ====================

    def table_exists(self, name: str) -> bool:
        """Check if table exists."""
        return self.schema.table_exists(name)

    def column_exists(self, table_name: str, column_name: str) -> bool:
        """Check if column exists in table."""
        return self.schema.column_exists(table_name, column_name)

    def get_table(self, name: str) -> Table | None:
        """Get table by name."""
        return self.schema.get_table(name)

    def get_columns(self, table_name: str) -> list[str]:
        """Get column names for a table."""
        table = self.get_table(table_name)
        return list(table.columns.keys()) if table else []

    def get_column(self, table_name: str, column_name: str) -> Column | None:
        """Get column metadata."""
        table = self.get_table(table_name)
        if not table:
            return None
        return table.columns.get(column_name.lower())

    def get_table_comment(self, table_name: str) -> str:
        """Get table description (Thai comment)."""
        table = self.get_table(table_name)
        return table.comment if table else ""

    def get_column_comment(self, table_name: str, column_name: str) -> str:
        """Get column description (Thai comment)."""
        column = self.get_column(table_name, column_name)
        return column.comment if column else ""

    # ==================== PHI Detection ====================

    def is_phi_column(self, column_name: str) -> bool:
        """Check if column is PHI."""
        return self.schema.is_phi_column(column_name)

    def get_phi_columns_in_table(self, table_name: str) -> list[str]:
        """Get PHI columns in a specific table."""
        table = self.get_table(table_name)
        if not table:
            return []
        return [c.name for c in table.columns.values() if c.is_phi]

    # ==================== Join Intelligence ====================

    def _build_join_graph(self) -> dict[str, list[JoinEdge]]:
        """Build adjacency list from join edges."""
        graph: dict[str, list[JoinEdge]] = {}

        for edge in self.schema.join_edges:
            # Add forward edge
            if edge.from_table not in graph:
                graph[edge.from_table] = []
            graph[edge.from_table].append(edge)

            # Add reverse edge (joins are bidirectional)
            reverse_edge = JoinEdge(
                from_table=edge.to_table,
                from_column=edge.to_column,
                to_table=edge.from_table,
                to_column=edge.from_column,
                confidence=edge.confidence,
                rel_type=edge.rel_type,
                source=edge.source,
                warning_from=edge.warning_to,
                warning_to=edge.warning_from,
            )
            if edge.to_table not in graph:
                graph[edge.to_table] = []
            graph[edge.to_table].append(reverse_edge)

        return graph

    def _score_edge(self, edge: JoinEdge) -> int:
        """Calculate score for a join edge."""
        base_score = CONFIDENCE_SCORES.get(edge.confidence, 0)
        type_bonus = REL_TYPE_BONUSES.get(edge.rel_type, 0)

        # Penalty for warnings
        warning_penalty = 0
        if edge.warning_from or edge.warning_to:
            warning_penalty = -30

        return base_score + type_bonus + warning_penalty

    def find_join_path(
        self,
        from_table: str,
        to_table: str,
        max_hops: int = 3,
    ) -> list[JoinPath]:
        """
        Find all join paths between two tables using BFS.

        Args:
            from_table: Source table
            to_table: Target table
            max_hops: Maximum number of joins (default 3)

        Returns:
            List of JoinPath, sorted by score (best first)
        """
        from_upper = from_table.upper()
        to_upper = to_table.upper()

        if from_upper == to_upper:
            return []

        if not self.table_exists(from_upper) or not self.table_exists(to_upper):
            return []

        graph = self._build_join_graph()
        paths: list[JoinPath] = []

        # BFS to find all paths up to max_hops
        # State: (current_table, path_so_far, visited)
        queue: deque[tuple[str, list[JoinEdge], set[str]]] = deque()
        queue.append((from_upper, [], {from_upper}))

        while queue:
            current, path, visited = queue.popleft()

            if len(path) > max_hops:
                continue

            # Check neighbors
            for edge in graph.get(current, []):
                next_table = edge.to_table

                if next_table in visited:
                    continue

                new_path = path + [edge]

                if next_table == to_upper:
                    # Found a path
                    steps = []
                    total_score = 0
                    warnings = []

                    for e in new_path:
                        score = self._score_edge(e)
                        step = JoinStep(
                            from_table=e.from_table,
                            from_column=e.from_column,
                            to_table=e.to_table,
                            to_column=e.to_column,
                            confidence=e.confidence,
                            rel_type=e.rel_type,
                            score=score,
                            warning=e.warning_from or e.warning_to,
                        )
                        steps.append(step)
                        total_score += score

                        if step.warning:
                            warnings.append(
                                f"{e.from_table}.{e.from_column}: {step.warning}"
                            )

                    paths.append(JoinPath(
                        from_table=from_upper,
                        to_table=to_upper,
                        steps=steps,
                        total_score=total_score,
                        warnings=warnings,
                    ))
                else:
                    # Continue searching
                    if len(new_path) < max_hops:
                        new_visited = visited | {next_table}
                        queue.append((next_table, new_path, new_visited))

        # Sort by: hop count (ascending), then score (descending)
        paths.sort(key=lambda p: (p.hop_count, -p.total_score))

        return paths

    def get_best_join(
        self,
        from_table: str,
        to_table: str,
    ) -> JoinPath | None:
        """Get the best (highest-scoring, shortest) join path."""
        paths = self.find_join_path(from_table, to_table)
        return paths[0] if paths else None

    def get_direct_joins(
        self,
        from_table: str,
        to_table: str,
    ) -> list[JoinStep]:
        """Get direct (single-hop) joins between tables, sorted by score."""
        from_upper = from_table.upper()
        to_upper = to_table.upper()

        steps = []
        for edge in self.schema.join_edges:
            if (edge.from_table == from_upper and edge.to_table == to_upper) or \
               (edge.from_table == to_upper and edge.to_table == from_upper):
                score = self._score_edge(edge)
                step = JoinStep(
                    from_table=edge.from_table,
                    from_column=edge.from_column,
                    to_table=edge.to_table,
                    to_column=edge.to_column,
                    confidence=edge.confidence,
                    rel_type=edge.rel_type,
                    score=score,
                    warning=edge.warning_from or edge.warning_to,
                )
                steps.append(step)

        # Sort by score descending
        steps.sort(key=lambda s: -s.score)
        return steps

    def validate_join(
        self,
        table_a: str,
        column_a: str,
        table_b: str,
        column_b: str,
    ) -> JoinValidation:
        """
        Validate a proposed join between two columns.

        Returns:
            JoinValidation with confidence, warnings, and suggestions
        """
        table_a_upper = table_a.upper()
        table_b_upper = table_b.upper()
        col_a_lower = column_a.lower()
        col_b_lower = column_b.lower()

        # Check if tables exist
        if not self.table_exists(table_a_upper):
            return JoinValidation(
                valid=False,
                confidence="heuristic",
                score=0,
                warnings=[f"Table {table_a_upper} not found"],
            )

        if not self.table_exists(table_b_upper):
            return JoinValidation(
                valid=False,
                confidence="heuristic",
                score=0,
                warnings=[f"Table {table_b_upper} not found"],
            )

        # Check if columns exist
        if not self.column_exists(table_a_upper, col_a_lower):
            return JoinValidation(
                valid=False,
                confidence="heuristic",
                score=0,
                warnings=[f"Column {table_a_upper}.{col_a_lower} not found"],
            )

        if not self.column_exists(table_b_upper, col_b_lower):
            return JoinValidation(
                valid=False,
                confidence="heuristic",
                score=0,
                warnings=[f"Column {table_b_upper}.{col_b_lower} not found"],
            )

        # Check if this join is in our known edges
        for edge in self.schema.join_edges:
            if (edge.from_table == table_a_upper and edge.from_column == col_a_lower and
                edge.to_table == table_b_upper and edge.to_column == col_b_lower) or \
               (edge.from_table == table_b_upper and edge.from_column == col_b_lower and
                edge.to_table == table_a_upper and edge.to_column == col_a_lower):

                score = self._score_edge(edge)
                warnings = []
                suggestion = ""

                if edge.warning_from or edge.warning_to:
                    warning = edge.warning_from or edge.warning_to
                    warnings.append(warning)

                    # Suggest better alternative if available
                    direct_joins = self.get_direct_joins(table_a_upper, table_b_upper)
                    better = [j for j in direct_joins if j.score > score and not j.warning]
                    if better:
                        suggestion = (
                            f"Consider using {better[0].from_table}.{better[0].from_column} = "
                            f"{better[0].to_table}.{better[0].to_column} instead "
                            f"(confidence: {better[0].confidence})"
                        )

                return JoinValidation(
                    valid=True,
                    confidence=edge.confidence,
                    score=score,
                    warnings=warnings,
                    suggestion=suggestion,
                )

        # Not a known join - check if columns share same name (heuristic)
        if col_a_lower == col_b_lower:
            return JoinValidation(
                valid=True,
                confidence="heuristic",
                score=25,
                warnings=["This join is not in the schema. Verify manually."],
            )

        return JoinValidation(
            valid=False,
            confidence="heuristic",
            score=0,
            warnings=["No known relationship between these columns"],
            suggestion=f"Check if {table_a_upper} and {table_b_upper} can be joined via another path",
        )

    def get_recommended_joins(
        self,
        tables: list[str],
        base_table: str | None = None,
    ) -> JoinRecommendation:
        """
        Get recommended joins for a set of tables.

        Uses a greedy algorithm to find optimal join order based on:
        1. Connection to already-joined tables
        2. Join confidence scores

        Args:
            tables: List of tables to join
            base_table: Starting table (default: first in list)

        Returns:
            JoinRecommendation with ordered joins
        """
        if not tables:
            return JoinRecommendation(tables=[], joins=[], total_score=0)

        tables_upper = [t.upper() for t in tables]
        base = (base_table or tables_upper[0]).upper()

        if base not in tables_upper:
            tables_upper = [base] + tables_upper

        joined = {base}
        remaining = set(tables_upper) - joined
        joins: list[JoinStep] = []
        warnings: list[str] = []
        total_score = 0

        while remaining:
            best_join: JoinStep | None = None
            best_target: str | None = None

            # Find best join from any joined table to any remaining table
            for joined_table in joined:
                for target in remaining:
                    path = self.get_best_join(joined_table, target)
                    if path and path.is_direct:
                        step = path.steps[0]
                        if best_join is None or step.score > best_join.score:
                            best_join = step
                            best_target = target

            if best_join and best_target:
                joins.append(best_join)
                total_score += best_join.score
                joined.add(best_target)
                remaining.remove(best_target)

                if best_join.warning:
                    warnings.append(
                        f"{best_join.from_table}.{best_join.from_column}: {best_join.warning}"
                    )
            else:
                # Can't find direct join - try multi-hop
                for target in list(remaining):
                    paths = self.find_join_path(list(joined)[0], target, max_hops=2)
                    if paths:
                        path = paths[0]
                        for step in path.steps:
                            if step.to_table not in joined:
                                joins.append(step)
                                total_score += step.score
                                joined.add(step.to_table)
                                if step.warning:
                                    warnings.append(
                                        f"{step.from_table}.{step.from_column}: {step.warning}"
                                    )
                        remaining.discard(target)
                        break
                else:
                    # Give up on remaining tables
                    warnings.append(f"Could not find join path to: {', '.join(remaining)}")
                    break

        return JoinRecommendation(
            tables=tables_upper,
            joins=joins,
            total_score=total_score,
            warnings=warnings,
        )

    # ==================== Backward Compatibility ====================

    def validate_sql_references(
        self,
        tables: list[str],
        columns: dict[str, list[str]],
    ) -> tuple[list[str], list[str]]:
        """
        Validate table and column references (backward compatible with old Catalog).

        Args:
            tables: List of table names used in query
            columns: Dict of table_name -> [column_names] used

        Returns:
            Tuple of (invalid_tables, invalid_columns)
        """
        invalid_tables = [t for t in tables if not self.table_exists(t)]
        invalid_columns = []

        for table_name, col_list in columns.items():
            if not self.table_exists(table_name):
                continue
            for col in col_list:
                if not self.column_exists(table_name, col):
                    invalid_columns.append(f"{table_name}.{col}")

        return invalid_tables, invalid_columns

    def find_join_paths(
        self,
        from_table: str,
        to_table: str,
    ) -> list[JoinEdge]:
        """
        Find relationships that connect two tables (backward compatible).
        Returns raw JoinEdge objects for compatibility.
        """
        from_upper = from_table.upper()
        to_upper = to_table.upper()

        return [
            edge for edge in self.schema.join_edges
            if (edge.from_table == from_upper and edge.to_table == to_upper)
            or (edge.from_table == to_upper and edge.to_table == from_upper)
        ]

    @property
    def tables(self) -> dict[str, Table]:
        """Get all tables (backward compatible)."""
        return self.schema.tables

    @property
    def families(self) -> dict[str, list[str]]:
        """Get table families (backward compatible)."""
        return self.schema.families

    @property
    def phi_columns(self) -> frozenset[str]:
        """Get PHI column names (backward compatible)."""
        return self.schema.phi_columns

    @property
    def universal_keys(self) -> frozenset[str]:
        """Get universal key names (backward compatible)."""
        return self.schema.universal_keys


# ==================== Module-level Functions ====================

# Singleton instance
_cached_catalog: SchemaCatalog | None = None


def get_schema_catalog(
    force_reload: bool = False,
) -> SchemaCatalog:
    """
    Get or initialize the global schema catalog instance.

    Args:
        force_reload: If True, reload from disk

    Returns:
        SchemaCatalog instance
    """
    global _cached_catalog

    if _cached_catalog is not None and not force_reload:
        return _cached_catalog

    schema = get_schema_knowledge(force_reload=force_reload)
    _cached_catalog = SchemaCatalog(schema)
    return _cached_catalog


def reset_schema_catalog() -> None:
    """Reset the global catalog instance."""
    global _cached_catalog
    _cached_catalog = None


# Backward-compatible aliases
def get_catalog() -> SchemaCatalog:
    """Alias for get_schema_catalog (backward compatible)."""
    return get_schema_catalog()


Catalog = SchemaCatalog  # Type alias for backward compatibility
