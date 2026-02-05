"""
Mermaid ER diagram parser -> structured catalog JSON.

Parses .mmd files to extract tables, columns, relationships,
and identifies PHI columns that must never appear in SELECT output.
"""

from __future__ import annotations

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

# Patterns that suggest PHI even if not in explicit list
PHI_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"^(patient_?)?name", re.IGNORECASE),
    re.compile(r"addr(ess)?", re.IGNORECASE),
    re.compile(r"phone|mobile|tel", re.IGNORECASE),
    re.compile(r"birth", re.IGNORECASE),
    re.compile(r"^id_?card", re.IGNORECASE),
)


@dataclass
class Column:
    name: str
    data_type: str
    is_pk: bool = False
    is_fk: bool = False
    fk_note: str | None = None
    is_phi: bool = False


@dataclass
class Relationship:
    from_table: str
    to_table: str
    join_key: str
    confidence: Literal["high", "medium"]


@dataclass
class Table:
    name: str
    columns: dict[str, Column] = field(default_factory=dict)
    additional_columns: int = 0  # "%% +N more" from diagram
    family: str = ""  # Table family prefix (e.g., "IPT", "OVST")


@dataclass
class Catalog:
    tables: dict[str, Table] = field(default_factory=dict)
    relationships: list[Relationship] = field(default_factory=list)
    phi_columns: set[str] = field(default_factory=set)
    families: dict[str, list[str]] = field(default_factory=dict)  # family -> table names
    universal_keys: frozenset[str] = field(default_factory=lambda: frozenset({"hn", "an", "vn"}))

    def table_exists(self, name: str) -> bool:
        """Check if table exists (case-insensitive)."""
        return name.upper() in self.tables

    def column_exists(self, table_name: str, column_name: str) -> bool:
        """Check if column exists in table."""
        table = self.tables.get(table_name.upper())
        if not table:
            return False
        return column_name.lower() in table.columns

    def get_table(self, name: str) -> Table | None:
        """Get table by name (case-insensitive)."""
        return self.tables.get(name.upper())

    def get_columns(self, table_name: str) -> list[str]:
        """Get column names for a table."""
        table = self.get_table(table_name)
        return list(table.columns.keys()) if table else []

    def get_phi_columns_in_table(self, table_name: str) -> list[str]:
        """Get PHI columns in a specific table."""
        table = self.get_table(table_name)
        if not table:
            return []
        return [c.name for c in table.columns.values() if c.is_phi]

    def get_family_tables(self, family: str) -> list[str]:
        """Get all tables in a family."""
        return self.families.get(family.upper(), [])

    def find_join_paths(self, from_table: str, to_table: str) -> list[Relationship]:
        """Find relationships that connect two tables."""
        from_upper = from_table.upper()
        to_upper = to_table.upper()
        return [
            r for r in self.relationships
            if (r.from_table == from_upper and r.to_table == to_upper)
            or (r.from_table == to_upper and r.to_table == from_upper)
        ]

    def validate_sql_references(
        self,
        tables: list[str],
        columns: dict[str, list[str]]
    ) -> tuple[list[str], list[str]]:
        """
        Validate table and column references.

        Args:
            tables: List of table names used in query
            columns: Dict of table_name -> [column_names] used

        Returns:
            Tuple of (invalid_tables, invalid_columns)
            where invalid_columns is list of "table.column" strings
        """
        invalid_tables = [t for t in tables if not self.table_exists(t)]
        invalid_columns = []

        for table_name, col_list in columns.items():
            if not self.table_exists(table_name):
                continue  # Already flagged as invalid table
            for col in col_list:
                if not self.column_exists(table_name, col):
                    invalid_columns.append(f"{table_name}.{col}")

        return invalid_tables, invalid_columns

    def to_dict(self) -> dict:
        return {
            "tables": {
                name: {
                    "name": t.name,
                    "family": t.family,
                    "columns": {
                        cname: {
                            "name": c.name,
                            "data_type": c.data_type,
                            "is_pk": c.is_pk,
                            "is_fk": c.is_fk,
                            "fk_note": c.fk_note,
                            "is_phi": c.is_phi,
                        }
                        for cname, c in t.columns.items()
                    },
                    "additional_columns": t.additional_columns,
                }
                for name, t in self.tables.items()
            },
            "relationships": [asdict(r) for r in self.relationships],
            "phi_columns": sorted(self.phi_columns),
            "families": {k: sorted(v) for k, v in self.families.items()},
            "universal_keys": sorted(self.universal_keys),
            "stats": {
                "total_tables": len(self.tables),
                "total_columns": sum(len(t.columns) for t in self.tables.values()),
                "total_relationships": len(self.relationships),
                "total_families": len(self.families),
            }
        }

    @classmethod
    def from_dict(cls, data: dict) -> Catalog:
        catalog = cls()
        for tname, tdata in data.get("tables", {}).items():
            table = Table(name=tdata["name"])
            table.additional_columns = tdata.get("additional_columns", 0)
            table.family = tdata.get("family", "")
            for cname, cdata in tdata.get("columns", {}).items():
                table.columns[cname] = Column(
                    name=cdata["name"],
                    data_type=cdata["data_type"],
                    is_pk=cdata.get("is_pk", False),
                    is_fk=cdata.get("is_fk", False),
                    fk_note=cdata.get("fk_note"),
                    is_phi=cdata.get("is_phi", False),
                )
            catalog.tables[tname] = table
        for rdata in data.get("relationships", []):
            catalog.relationships.append(Relationship(**rdata))
        catalog.phi_columns = set(data.get("phi_columns", []))
        catalog.families = {k: list(v) for k, v in data.get("families", {}).items()}
        return catalog


def is_phi_column(column_name: str) -> bool:
    """Check if a column name indicates PHI data."""
    lower_name = column_name.lower()
    if lower_name in PHI_COLUMNS:
        return True
    return any(pattern.search(lower_name) for pattern in PHI_PATTERNS)


def infer_family(table_name: str) -> str:
    """Infer table family from table name prefix."""
    # Common prefixes (sorted by length descending for greedy matching)
    prefixes = [
        "EYESCREEN", "IPTBOOK", "DCTORDER", "IPTADM", "OPDDCT",
        "OPDLED", "OPPOST", "OPPROC", "LVSTEXM", "LABEXM",
        "MEDITEM", "PTTYPE", "BDVST", "DLVST", "PRSC",
        "OVST", "IPT", "MED", "LAB", "PT", "RM", "BD", "CN",
        "WARD", "MAST", "ANC", "RDO", "MOL", "MOTP", "LCT",
    ]
    upper_name = table_name.upper()
    for prefix in prefixes:
        if upper_name.startswith(prefix):
            return prefix

    # Fall back to first 2-4 characters as family
    for length in [4, 3, 2]:
        if len(table_name) >= length:
            prefix = table_name[:length].upper()
            if prefix.isalpha():
                return prefix

    return table_name.upper()


def parse_mermaid_er(content: str) -> Catalog:
    """
    Parse Mermaid ER diagram content into a Catalog.

    Handles:
    - Table blocks: TableName { ... }
    - Column definitions: type column_name [PK] [FK] ["note"]
    - Additional columns: %% +N more
    - Family comments: %% ===== FAMILY_NAME Family =====
    - Relationships: Table1 }o--|| Table2 : "key" (high confidence)
    - Relationships: Table1 }o..|| Table2 : "key" (medium confidence)
    """
    catalog = Catalog()

    # Pattern for family comments
    family_comment_pattern = re.compile(r"%%\s*=+\s*(\w+)\s+Family\s*=+")

    # Pattern for table blocks - must start with uppercase letter
    # Excludes relationship markers like }o--o{
    table_pattern = re.compile(
        r"^\s*([A-Z][A-Z0-9_]*)\s*\{([^}]*)\}",
        re.MULTILINE | re.DOTALL
    )

    # Pattern for column definitions
    # Format: type column_name [PK] [FK] ["note"]
    column_pattern = re.compile(
        r"^\s*(\w+)\s+(\w+)(?:\s+(PK))?(?:\s+(FK))?(?:\s+\"([^\"]*)\")?\s*$",
        re.MULTILINE
    )

    # Build a map of table positions to their preceding family comments
    table_families: dict[str, str] = {}
    current_family = ""
    lines = content.splitlines()
    for i, line in enumerate(lines):
        family_match = family_comment_pattern.search(line)
        if family_match:
            current_family = family_match.group(1).upper()
        # Check if this line starts a table definition
        if re.match(r"^\s*[A-Z][A-Z0-9_]*\s*\{", line):
            table_match = re.match(r"^\s*([A-Z][A-Z0-9_]*)", line)
            if table_match:
                table_name = table_match.group(1).upper()
                if current_family:
                    table_families[table_name] = current_family

    # Pattern for "more columns" comments
    more_pattern = re.compile(r"%%\s*\+(\d+)\s*more")

    # Pattern for relationships (solid line = high confidence)
    rel_solid_pattern = re.compile(
        r"(\w+)\s*\}o--\|\|\s*(\w+)\s*:\s*\"([^\"]+)\""
    )

    # Pattern for relationships (dotted line = medium confidence)
    rel_dotted_pattern = re.compile(
        r"(\w+)\s*\}o\.\.\|\|\s*(\w+)\s*:\s*\"([^\"]+)\""
    )

    # Also handle }o--o{ pattern (many-to-many in families diagram)
    rel_many_pattern = re.compile(
        r"(\w+)\s*\}o--o\{\s*(\w+)\s*:\s*\"([^\"]+)\""
    )

    # Parse table blocks
    for match in table_pattern.finditer(content):
        table_name = match.group(1).upper()
        block_content = match.group(2)

        # Assign family from comment or infer from name
        family = table_families.get(table_name, infer_family(table_name))
        table = Table(name=table_name, family=family)

        # Check for "more columns" indicator
        more_match = more_pattern.search(block_content)
        if more_match:
            table.additional_columns = int(more_match.group(1))

        # Parse columns
        for col_match in column_pattern.finditer(block_content):
            data_type = col_match.group(1)
            col_name = col_match.group(2).lower()
            is_pk = col_match.group(3) == "PK"
            is_fk = col_match.group(4) == "FK"
            fk_note = col_match.group(5)

            # Skip if this looks like a comment/count (e.g., "int tables")
            if col_name == "tables":
                continue

            column = Column(
                name=col_name,
                data_type=data_type,
                is_pk=is_pk,
                is_fk=is_fk,
                fk_note=fk_note,
                is_phi=is_phi_column(col_name),
            )
            table.columns[col_name] = column

            if column.is_phi:
                catalog.phi_columns.add(col_name)

        catalog.tables[table_name] = table

    # Parse relationships (high confidence - solid lines)
    for match in rel_solid_pattern.finditer(content):
        catalog.relationships.append(Relationship(
            from_table=match.group(1).upper(),
            to_table=match.group(2).upper(),
            join_key=match.group(3),
            confidence="high",
        ))

    # Parse relationships (medium confidence - dotted lines)
    for match in rel_dotted_pattern.finditer(content):
        catalog.relationships.append(Relationship(
            from_table=match.group(1).upper(),
            to_table=match.group(2).upper(),
            join_key=match.group(3),
            confidence="medium",
        ))

    # Parse many-to-many relationships
    for match in rel_many_pattern.finditer(content):
        # Split multiple keys if comma-separated
        keys = match.group(3).split(",")
        for key in keys:
            catalog.relationships.append(Relationship(
                from_table=match.group(1).upper(),
                to_table=match.group(2).upper(),
                join_key=key.strip(),
                confidence="high",
            ))

    return catalog


def load_catalog(catalog_path: Path) -> Catalog:
    """Load catalog from JSON file."""
    with open(catalog_path) as f:
        return Catalog.from_dict(json.load(f))


def save_catalog(catalog: Catalog, output_path: Path) -> None:
    """Save catalog to JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(catalog.to_dict(), f, indent=2)


def generate_catalog(
    schema_dir: Path | None = None,
    output_path: Path | None = None,
) -> Catalog:
    """
    Generate catalog from all .mmd files in schema directory.

    Args:
        schema_dir: Directory containing .mmd files (default: schema/)
        output_path: Where to save catalog.json (default: out/catalog.json)

    Returns:
        Combined Catalog from all parsed files
    """
    base_dir = Path(__file__).parent.parent
    schema_dir = schema_dir or base_dir / "schema"
    output_path = output_path or base_dir / "out" / "catalog.json"

    combined = Catalog()

    for mmd_file in schema_dir.glob("*.mmd"):
        content = mmd_file.read_text()
        parsed = parse_mermaid_er(content)

        # Merge tables (detailed diagram takes precedence)
        for name, table in parsed.tables.items():
            if name not in combined.tables or len(table.columns) > len(combined.tables[name].columns):
                combined.tables[name] = table

        # Merge relationships (deduplicate)
        existing_rels = {
            (r.from_table, r.to_table, r.join_key)
            for r in combined.relationships
        }
        for rel in parsed.relationships:
            key = (rel.from_table, rel.to_table, rel.join_key)
            if key not in existing_rels:
                combined.relationships.append(rel)
                existing_rels.add(key)

        # Merge PHI columns
        combined.phi_columns.update(parsed.phi_columns)

    # Build families dictionary from table family assignments
    families: dict[str, list[str]] = {}
    for table_name, table in combined.tables.items():
        family = table.family or infer_family(table_name)
        if family not in families:
            families[family] = []
        families[family].append(table_name)

    # Sort tables within each family
    combined.families = {k: sorted(v) for k, v in families.items()}

    save_catalog(combined, output_path)
    print(f"Generated catalog with {len(combined.tables)} tables, "
          f"{sum(len(t.columns) for t in combined.tables.values())} columns, "
          f"{len(combined.relationships)} relationships, "
          f"{len(combined.families)} families")

    return combined


def get_table_names(catalog: Catalog) -> set[str]:
    """Get all table names (lowercase for comparison)."""
    return {name.lower() for name in catalog.tables}


def get_column_names(catalog: Catalog, table_name: str) -> set[str]:
    """Get column names for a table (lowercase)."""
    table = catalog.tables.get(table_name.upper())
    if not table:
        return set()
    return set(table.columns.keys())


def table_has_column(catalog: Catalog, table_name: str, column_name: str) -> bool:
    """Check if a table has a specific column."""
    table = catalog.tables.get(table_name.upper())
    if not table:
        return False
    # Check explicit columns
    if column_name.lower() in table.columns:
        return True
    # If table has additional columns, we can't definitively say it doesn't exist
    # But for safety, we only allow explicitly cataloged columns
    return False


# Singleton catalog instance for runtime use
_cached_catalog: Catalog | None = None


def get_catalog(
    schema_dir: Path | None = None,
    catalog_path: Path | None = None,
    force_reload: bool = False,
) -> Catalog:
    """
    Get or initialize the global catalog instance.

    Priority:
    1. Return cached catalog if available (unless force_reload)
    2. Load from catalog_path (out/catalog.json) if exists
    3. Generate from schema_dir (.mmd files)

    Args:
        schema_dir: Directory containing .mmd files
        catalog_path: Path to catalog.json
        force_reload: If True, regenerate from .mmd files

    Returns:
        Catalog instance
    """
    global _cached_catalog

    if _cached_catalog is not None and not force_reload:
        return _cached_catalog

    base_dir = Path(__file__).parent.parent
    catalog_path = catalog_path or base_dir / "out" / "catalog.json"
    schema_dir = schema_dir or base_dir / "schema"

    # Try loading from JSON first (faster)
    if catalog_path.exists() and not force_reload:
        _cached_catalog = load_catalog(catalog_path)
        return _cached_catalog

    # Generate from .mmd files
    _cached_catalog = generate_catalog(schema_dir, catalog_path)
    return _cached_catalog


def reset_catalog() -> None:
    """Reset the global catalog instance (useful for testing)."""
    global _cached_catalog
    _cached_catalog = None


if __name__ == "__main__":
    generate_catalog()
