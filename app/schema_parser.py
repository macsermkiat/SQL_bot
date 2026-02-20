"""
Schema Parser - Parse CSV schema files into structured schema knowledge.

Parses:
- frequent_table.csv: Table names and descriptions
- frequent_column_enriched.csv: Column metadata with PK/FK info
- join_edges.csv: Explicit join mappings with confidence levels

Generates:
- out/schema_knowledge.json: Unified schema knowledge for SQL generation
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal

# PHI columns that must NEVER appear in SELECT output
PHI_COLUMNS: frozenset[str] = frozenset({
    # Patient identifiers
    "hn", "cid", "passport", "mrn", "national_id", "idcard", "pid",
    # Names
    "fname", "lname", "mname", "pname", "name", "fullname",
    "firstname", "lastname", "middlename", "prename",
    # Contact info
    "phone", "mobile", "tel", "telephone", "email", "fax",
    # Address
    "address", "addrpart", "moo", "road", "tambon", "amphur",
    "province", "zipcode", "postcode", "homeaddr", "workaddr",
    # Date of birth (exact)
    "dob", "birthdate", "birthday", "bdate",
    # Other quasi-identifiers
    "ssn", "social_security", "insurance_id", "member_id",
})

# Universal keys that connect tables across the system
UNIVERSAL_KEYS: frozenset[str] = frozenset({"hn", "an", "vn"})


ConfidenceLevel = Literal["high", "medium", "heuristic"]


@dataclass
class FKTarget:
    """Foreign key target with confidence."""
    table: str
    column: str
    confidence: ConfidenceLevel
    rel_type: str  # "universal", "table match", "within_family", "heuristic_home"


@dataclass
class Column:
    """Column metadata."""
    name: str
    data_type: str
    base_type: str
    comment: str
    is_pk: bool = False
    pk_confidence: str = ""
    pk_reason: str = ""
    is_fk: bool = False
    fk_targets: list[FKTarget] = field(default_factory=list)
    join_peers: list[str] = field(default_factory=list)  # "TABLE.column" format
    join_warning: str = ""
    is_phi: bool = False
    correction_note: str = ""       # Warning about common mistakes
    requires_join_table: str = ""   # Header table needed for hn/vn
    performance_hint: str = ""      # Performance guidance


@dataclass
class Table:
    """Table metadata."""
    name: str
    comment: str
    column_count: int
    columns: dict[str, Column] = field(default_factory=dict)
    family: str = ""


@dataclass
class JoinEdge:
    """Explicit join relationship between tables."""
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    confidence: ConfidenceLevel
    rel_type: str
    source: str
    warning_from: str = ""
    warning_to: str = ""


@dataclass
class DetailTableInfo:
    """Detail table that must join through family header for universal keys."""
    table_name: str
    missing_keys: list[str]       # e.g., ["hn"]
    has_keys: list[str]           # e.g., ["an"]
    join_column: str              # e.g., "an"
    header_join_column: str       # e.g., "an"


@dataclass
class FamilyHeaderInfo:
    """Family header table and its detail tables needing join guidance."""
    header_table: str
    header_keys: list[str]        # e.g., ["hn", "an"]
    details: list[DetailTableInfo] = field(default_factory=list)


@dataclass
class SchemaKnowledge:
    """Complete schema knowledge for SQL generation."""
    tables: dict[str, Table] = field(default_factory=dict)
    join_edges: list[JoinEdge] = field(default_factory=list)
    universal_keys: frozenset[str] = field(default_factory=lambda: UNIVERSAL_KEYS)
    families: dict[str, list[str]] = field(default_factory=dict)
    family_headers: dict[str, FamilyHeaderInfo] = field(default_factory=dict)
    phi_columns: frozenset[str] = field(default_factory=lambda: PHI_COLUMNS)

    def get_table(self, name: str) -> Table | None:
        """Get table by name (case-insensitive)."""
        return self.tables.get(name.upper())

    def table_exists(self, name: str) -> bool:
        """Check if table exists."""
        return name.upper() in self.tables

    def column_exists(self, table_name: str, column_name: str) -> bool:
        """Check if column exists in table."""
        table = self.get_table(table_name)
        if not table:
            return False
        return column_name.lower() in table.columns

    def get_join_options(
        self,
        from_table: str,
        to_table: str,
    ) -> list[JoinEdge]:
        """Get all join options between two tables, sorted by confidence."""
        from_upper = from_table.upper()
        to_upper = to_table.upper()

        options = [
            e for e in self.join_edges
            if (e.from_table == from_upper and e.to_table == to_upper)
            or (e.from_table == to_upper and e.to_table == from_upper)
        ]

        # Sort by confidence: high > medium > heuristic
        confidence_order = {"high": 0, "medium": 1, "heuristic": 2}
        return sorted(options, key=lambda e: confidence_order.get(e.confidence, 3))

    def get_fk_targets(self, table_name: str, column_name: str) -> list[FKTarget]:
        """Get FK targets for a column."""
        table = self.get_table(table_name)
        if not table:
            return []
        column = table.columns.get(column_name.lower())
        if not column:
            return []
        return column.fk_targets

    def get_tables_with_column(self, column_name: str) -> list[str]:
        """Find all tables that have a specific column."""
        col_lower = column_name.lower()
        return [
            table.name for table in self.tables.values()
            if col_lower in table.columns
        ]

    def is_phi_column(self, column_name: str) -> bool:
        """Check if column is PHI."""
        return column_name.lower() in self.phi_columns

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "tables": {
                name: {
                    "name": t.name,
                    "comment": t.comment,
                    "column_count": t.column_count,
                    "family": t.family,
                    "columns": {
                        cname: {
                            "name": c.name,
                            "data_type": c.data_type,
                            "base_type": c.base_type,
                            "comment": c.comment,
                            "is_pk": c.is_pk,
                            "pk_confidence": c.pk_confidence,
                            "pk_reason": c.pk_reason,
                            "is_fk": c.is_fk,
                            "fk_targets": [
                                {
                                    "table": ft.table,
                                    "column": ft.column,
                                    "confidence": ft.confidence,
                                    "rel_type": ft.rel_type,
                                }
                                for ft in c.fk_targets
                            ],
                            "join_peers": c.join_peers,
                            "join_warning": c.join_warning,
                            "is_phi": c.is_phi,
                            "correction_note": c.correction_note,
                            "requires_join_table": c.requires_join_table,
                            "performance_hint": c.performance_hint,
                        }
                        for cname, c in t.columns.items()
                    },
                }
                for name, t in self.tables.items()
            },
            "join_edges": [
                {
                    "from_table": e.from_table,
                    "from_column": e.from_column,
                    "to_table": e.to_table,
                    "to_column": e.to_column,
                    "confidence": e.confidence,
                    "rel_type": e.rel_type,
                    "source": e.source,
                    "warning_from": e.warning_from,
                    "warning_to": e.warning_to,
                }
                for e in self.join_edges
            ],
            "universal_keys": sorted(self.universal_keys),
            "families": {k: sorted(v) for k, v in self.families.items()},
            "family_headers": {
                header: {
                    "header_table": info.header_table,
                    "header_keys": info.header_keys,
                    "details": [
                        {
                            "table_name": d.table_name,
                            "missing_keys": d.missing_keys,
                            "has_keys": d.has_keys,
                            "join_column": d.join_column,
                            "header_join_column": d.header_join_column,
                        }
                        for d in info.details
                    ],
                }
                for header, info in self.family_headers.items()
            },
            "phi_columns": sorted(self.phi_columns),
            "stats": {
                "total_tables": len(self.tables),
                "total_columns": sum(len(t.columns) for t in self.tables.values()),
                "total_join_edges": len(self.join_edges),
                "total_families": len(self.families),
                "total_family_headers": len(self.family_headers),
                "total_detail_tables": sum(
                    len(fh.details) for fh in self.family_headers.values()
                ),
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> SchemaKnowledge:
        """Load from JSON dict."""
        schema = cls()

        # Load tables and columns
        for tname, tdata in data.get("tables", {}).items():
            table = Table(
                name=tdata["name"],
                comment=tdata.get("comment", ""),
                column_count=tdata.get("column_count", 0),
                family=tdata.get("family", ""),
            )

            for cname, cdata in tdata.get("columns", {}).items():
                fk_targets = [
                    FKTarget(
                        table=ft["table"],
                        column=ft["column"],
                        confidence=ft["confidence"],
                        rel_type=ft["rel_type"],
                    )
                    for ft in cdata.get("fk_targets", [])
                ]

                column = Column(
                    name=cdata["name"],
                    data_type=cdata.get("data_type", ""),
                    base_type=cdata.get("base_type", ""),
                    comment=cdata.get("comment", ""),
                    is_pk=cdata.get("is_pk", False),
                    pk_confidence=cdata.get("pk_confidence", ""),
                    pk_reason=cdata.get("pk_reason", ""),
                    is_fk=cdata.get("is_fk", False),
                    fk_targets=fk_targets,
                    join_peers=cdata.get("join_peers", []),
                    join_warning=cdata.get("join_warning", ""),
                    is_phi=cdata.get("is_phi", False),
                    correction_note=cdata.get("correction_note", ""),
                    requires_join_table=cdata.get("requires_join_table", ""),
                    performance_hint=cdata.get("performance_hint", ""),
                )
                table.columns[cname] = column

            schema.tables[tname] = table

        # Load join edges
        for edata in data.get("join_edges", []):
            schema.join_edges.append(JoinEdge(
                from_table=edata["from_table"],
                from_column=edata["from_column"],
                to_table=edata["to_table"],
                to_column=edata["to_column"],
                confidence=edata["confidence"],
                rel_type=edata["rel_type"],
                source=edata.get("source", ""),
                warning_from=edata.get("warning_from", ""),
                warning_to=edata.get("warning_to", ""),
            ))

        # Load metadata
        schema.families = {k: list(v) for k, v in data.get("families", {}).items()}

        # Load family headers
        for header, hdata in data.get("family_headers", {}).items():
            details = [
                DetailTableInfo(
                    table_name=d["table_name"],
                    missing_keys=d["missing_keys"],
                    has_keys=d["has_keys"],
                    join_column=d["join_column"],
                    header_join_column=d["header_join_column"],
                )
                for d in hdata.get("details", [])
            ]
            schema.family_headers[header] = FamilyHeaderInfo(
                header_table=hdata["header_table"],
                header_keys=hdata["header_keys"],
                details=details,
            )

        return schema


def _parse_fk_targets(fk_targets_str: str) -> list[FKTarget]:
    """
    Parse fk_targets string like 'PT.hn(high:universal); IPT.an(medium:within_family)'
    """
    if not fk_targets_str or fk_targets_str.strip() == "":
        return []

    targets = []
    # Split by semicolon
    parts = [p.strip() for p in fk_targets_str.split(";") if p.strip()]

    for part in parts:
        # Pattern: TABLE.column(confidence:rel_type)
        match = re.match(r"(\w+)\.(\w+)\((\w+):([^)]+)\)", part)
        if match:
            targets.append(FKTarget(
                table=match.group(1).upper(),
                column=match.group(2).lower(),
                confidence=match.group(3),
                rel_type=match.group(4),
            ))
        else:
            # Try simpler pattern: TABLE.column
            simple_match = re.match(r"(\w+)\.(\w+)", part)
            if simple_match:
                targets.append(FKTarget(
                    table=simple_match.group(1).upper(),
                    column=simple_match.group(2).lower(),
                    confidence="medium",
                    rel_type="unknown",
                ))

    return targets


def _parse_join_peers(join_peers_str: str) -> list[str]:
    """Parse join_peers string like 'PT.hn; IPT.an; OVST.vn'"""
    if not join_peers_str or join_peers_str.strip() == "":
        return []

    return [p.strip() for p in join_peers_str.split(";") if p.strip()]


def _infer_family(table_name: str) -> str:
    """Infer table family from table name prefix."""
    prefixes = [
        "EYESCREEN", "IPTBOOK", "DCTORDER", "IPTADM", "OPDDCT",
        "OPDLED", "OPPOST", "OPPROC", "LVSTEXM", "LABEXM",
        "MEDITEM", "PTTYPE", "BDVST", "DLVST", "PRSC",
        "OVST", "IPT", "MED", "LAB", "PT", "RM", "BD", "CN",
        "WARD", "MAST", "ANC", "RDO", "MOL", "MOTP", "LCT",
        "ARPT", "INCPT",
    ]
    upper_name = table_name.upper()
    for prefix in sorted(prefixes, key=len, reverse=True):  # Longest first
        if upper_name.startswith(prefix):
            return prefix

    # Fall back to first 2-4 characters
    for length in [4, 3, 2]:
        if len(table_name) >= length:
            prefix = table_name[:length].upper()
            if prefix.isalpha():
                return prefix

    return table_name.upper()


def parse_frequent_tables(csv_path: Path) -> dict[str, Table]:
    """Parse frequent_table.csv for table metadata."""
    tables: dict[str, Table] = {}

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            table_name = row.get("table_name", "").strip().upper()
            if not table_name:
                continue

            tables[table_name] = Table(
                name=table_name,
                comment=row.get("comment", "").strip(),
                column_count=int(row.get("column_count", 0) or 0),
                family=_infer_family(table_name),
            )

    return tables


def parse_frequent_columns(
    csv_path: Path,
    tables: dict[str, Table],
) -> dict[str, Table]:
    """Parse frequent_column_enriched.csv for column metadata."""

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            table_name = row.get("table_name", "").strip().upper()
            column_name = row.get("column_name", "").strip().lower()

            if not table_name or not column_name:
                continue

            # Create table if not exists (from column file)
            if table_name not in tables:
                tables[table_name] = Table(
                    name=table_name,
                    comment="",
                    column_count=0,
                    family=_infer_family(table_name),
                )

            # Parse FK targets
            fk_targets = _parse_fk_targets(row.get("fk_targets", ""))

            # Parse join peers
            join_peers = _parse_join_peers(row.get("join_peers", ""))

            # Determine if PHI
            is_phi = column_name in PHI_COLUMNS

            column = Column(
                name=column_name,
                data_type=row.get("database_type", "").strip(),
                base_type=row.get("base_type", "").strip(),
                comment=row.get("comment", "").strip(),
                is_pk=row.get("is_pk", "0") == "1",
                pk_confidence=row.get("pk_confidence", "").strip(),
                pk_reason=row.get("pk_reason", "").strip(),
                is_fk=row.get("is_fk", "0") == "1",
                fk_targets=fk_targets,
                join_peers=join_peers,
                join_warning=row.get("join_warning", "").strip(),
                is_phi=is_phi,
                correction_note=row.get("correction_note", "").strip(),
                requires_join_table=row.get("requires_join_table", "").strip(),
                performance_hint=row.get("performance_hint", "").strip(),
            )

            tables[table_name].columns[column_name] = column

    return tables


def parse_join_edges(csv_path: Path) -> list[JoinEdge]:
    """Parse join_edges.csv for explicit join mappings."""
    edges: list[JoinEdge] = []

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            from_table = row.get("from_table", "").strip().upper()
            to_table = row.get("to_table", "").strip().upper()

            if not from_table or not to_table:
                continue

            edge = JoinEdge(
                from_table=from_table,
                from_column=row.get("from_column", "").strip().lower(),
                to_table=to_table,
                to_column=row.get("to_column", "").strip().lower(),
                confidence=row.get("confidence", "medium").strip(),
                rel_type=row.get("rel_type", "").strip(),
                source=row.get("source", "").strip(),
                warning_from=row.get("warnings_from", "").strip(),
                warning_to=row.get("warnings_to", "").strip(),
            )
            edges.append(edge)

    return edges


def build_families(tables: dict[str, Table]) -> dict[str, list[str]]:
    """Build family -> table_names mapping."""
    families: dict[str, list[str]] = {}

    for table in tables.values():
        family = table.family or _infer_family(table.name)
        if family not in families:
            families[family] = []
        families[family].append(table.name)

    # Sort tables within each family
    return {k: sorted(v) for k, v in families.items()}


def _find_detail_join_column(
    detail_table: str,
    header_table: str,
    join_edges: list[JoinEdge],
    tables: dict[str, Table],
) -> tuple[str, str]:
    """Find the best join column between a detail and its header table.

    Returns (detail_col, header_col) or ("", "") if none found.
    Prefers non-universal keys (more specific) over universal keys.
    """
    universal = {"hn", "an", "vn"}
    conf_scores = {"high": 3, "medium": 2, "heuristic": 1}
    candidates: list[tuple[int, str, str]] = []

    for edge in join_edges:
        detail_col = ""
        header_col = ""

        if edge.from_table == detail_table and edge.to_table == header_table:
            detail_col = edge.from_column
            header_col = edge.to_column
        elif edge.from_table == header_table and edge.to_table == detail_table:
            detail_col = edge.to_column
            header_col = edge.from_column
        else:
            continue

        score = 0
        if detail_col not in universal:
            score += 10  # Strongly prefer specific join keys
        score += conf_scores.get(edge.confidence, 0)
        candidates.append((score, detail_col, header_col))

    if candidates:
        candidates.sort(key=lambda x: -x[0])
        return candidates[0][1], candidates[0][2]

    # Fallback: shared non-universal columns
    detail_t = tables.get(detail_table)
    header_t = tables.get(header_table)
    if detail_t and header_t:
        shared = (
            set(detail_t.columns.keys()) - universal
        ) & (
            set(header_t.columns.keys()) - universal
        )
        if shared:
            col = sorted(shared)[0]
            return col, col

    # Last resort: shared universal keys (prefer an > vn > hn)
    if detail_t and header_t:
        shared_uk = (
            {c for c in detail_t.columns if c in universal}
            & {c for c in header_t.columns if c in universal}
        )
        for key in ["an", "vn", "hn"]:
            if key in shared_uk:
                return key, key

    return "", ""


def detect_family_headers(
    tables: dict[str, Table],
    families: dict[str, list[str]],
    join_edges: list[JoinEdge],
) -> dict[str, FamilyHeaderInfo]:
    """Auto-detect family header tables and detail tables missing universal keys.

    For each table family with 2+ members, identifies:
    - The header table (member with the most universal keys)
    - Detail tables missing universal keys vs the header
    - Join columns to reach the header from each detail

    Excludes:
    - Lookup/reference tables (<=3 columns and no universal keys)
    - Home tables (PT, IPT, OVST) from being flagged as details
    """
    universal = {"hn", "an", "vn"}
    home_tables = {"PT", "IPT", "OVST"}

    # Which universal keys each table actually has as columns
    table_keys: dict[str, set[str]] = {}
    for tname, table in tables.items():
        table_keys[tname] = {col for col in table.columns if col in universal}

    result: dict[str, FamilyHeaderInfo] = {}

    for family_name, members in families.items():
        if len(members) < 2:
            continue

        # Filter out lookup/reference tables
        candidate_members = []
        for m in members:
            t = tables.get(m)
            if not t:
                continue
            keys = table_keys.get(m, set())
            if len(t.columns) <= 3 and not keys:
                continue
            candidate_members.append(m)

        if len(candidate_members) < 2:
            continue

        # Header = member with the most universal keys
        # Home tables (PT, IPT, OVST) always preferred as headers
        # Tie-break: prefer exact family name match, then shortest name
        family_upper = family_name.upper()
        header = max(
            candidate_members,
            key=lambda m: (
                1 if m in home_tables else 0,
                len(table_keys.get(m, set())),
                1 if m == family_upper else 0,
                -len(m),
            ),
        )
        header_keys = table_keys.get(header, set())

        if not header_keys:
            continue

        # Find detail tables missing keys relative to header
        details: list[DetailTableInfo] = []
        for m in candidate_members:
            if m == header or m in home_tables:
                continue

            m_keys = table_keys.get(m, set())
            missing = header_keys - m_keys

            if not missing:
                continue

            join_col, header_join_col = _find_detail_join_column(
                m, header, join_edges, tables,
            )

            if not join_col:
                continue

            details.append(DetailTableInfo(
                table_name=m,
                missing_keys=sorted(missing),
                has_keys=sorted(m_keys),
                join_column=join_col,
                header_join_column=header_join_col,
            ))

        if details:
            result[header] = FamilyHeaderInfo(
                header_table=header,
                header_keys=sorted(header_keys),
                details=sorted(details, key=lambda d: d.table_name),
            )

    return result


def generate_schema_knowledge(
    schema_dir: Path | None = None,
    output_path: Path | None = None,
) -> SchemaKnowledge:
    """
    Generate schema knowledge from CSV files.

    Args:
        schema_dir: Directory containing CSV files (default: schema/)
        output_path: Where to save schema_knowledge.json (default: out/schema_knowledge.json)

    Returns:
        SchemaKnowledge instance
    """
    base_dir = Path(__file__).parent.parent
    schema_dir = schema_dir or base_dir / "schema"
    output_path = output_path or base_dir / "out" / "schema_knowledge.json"

    # Parse tables
    tables_path = schema_dir / "frequent_table.csv"
    if tables_path.exists():
        tables = parse_frequent_tables(tables_path)
    else:
        tables = {}
        print(f"Warning: {tables_path} not found")

    # Parse columns (enriches tables dict)
    columns_path = schema_dir / "frequent_column_enriched.csv"
    if columns_path.exists():
        tables = parse_frequent_columns(columns_path, tables)
    else:
        print(f"Warning: {columns_path} not found")

    # Parse join edges
    edges_path = schema_dir / "join_edges.csv"
    if edges_path.exists():
        join_edges = parse_join_edges(edges_path)
    else:
        join_edges = []
        print(f"Warning: {edges_path} not found")

    # Build families
    families = build_families(tables)

    # Detect family headers and detail tables
    family_headers = detect_family_headers(tables, families, join_edges)

    # Create schema knowledge
    schema = SchemaKnowledge(
        tables=tables,
        join_edges=join_edges,
        families=families,
        family_headers=family_headers,
    )

    # Save to JSON
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(schema.to_dict(), f, indent=2, ensure_ascii=False)

    detail_count = sum(len(fh.details) for fh in schema.family_headers.values())
    print(f"Generated schema knowledge:")
    print(f"  - Tables: {len(schema.tables)}")
    print(f"  - Columns: {sum(len(t.columns) for t in schema.tables.values())}")
    print(f"  - Join edges: {len(schema.join_edges)}")
    print(f"  - Families: {len(schema.families)}")
    print(f"  - Family headers: {len(schema.family_headers)} ({detail_count} detail tables)")
    print(f"  - Output: {output_path}")

    return schema


def load_schema_knowledge(path: Path | None = None) -> SchemaKnowledge:
    """Load schema knowledge from JSON file."""
    if path is None:
        path = Path(__file__).parent.parent / "out" / "schema_knowledge.json"

    with open(path, encoding="utf-8") as f:
        return SchemaKnowledge.from_dict(json.load(f))


# Singleton instance
_cached_schema: SchemaKnowledge | None = None


def get_schema_knowledge(
    schema_dir: Path | None = None,
    schema_path: Path | None = None,
    force_reload: bool = False,
) -> SchemaKnowledge:
    """
    Get or initialize the global schema knowledge instance.

    Priority:
    1. Return cached schema if available (unless force_reload)
    2. Load from schema_path (out/schema_knowledge.json) if exists
    3. Generate from schema_dir (CSV files)

    Args:
        schema_dir: Directory containing CSV files
        schema_path: Path to schema_knowledge.json
        force_reload: If True, regenerate from CSV files

    Returns:
        SchemaKnowledge instance
    """
    global _cached_schema

    if _cached_schema is not None and not force_reload:
        return _cached_schema

    base_dir = Path(__file__).parent.parent
    schema_path = schema_path or base_dir / "out" / "schema_knowledge.json"
    schema_dir = schema_dir or base_dir / "schema"

    # Try loading from JSON first (faster)
    if schema_path.exists() and not force_reload:
        _cached_schema = load_schema_knowledge(schema_path)
        return _cached_schema

    # Generate from CSV files
    _cached_schema = generate_schema_knowledge(schema_dir, schema_path)
    return _cached_schema


def reset_schema_knowledge() -> None:
    """Reset the global schema knowledge instance."""
    global _cached_schema
    _cached_schema = None


if __name__ == "__main__":
    generate_schema_knowledge()
