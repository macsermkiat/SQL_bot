"""
Tests for catalog parsing from Mermaid ER diagrams.
"""

import pytest
from app.catalog import (
    parse_mermaid_er,
    is_phi_column,
    infer_family,
    Catalog,
    Table,
    Column,
    Relationship,
)


class TestMermaidParsing:
    """Test parsing of Mermaid ER diagram syntax."""

    def test_parse_simple_table(self):
        """Parse a simple table definition."""
        content = """
        erDiagram
            PT {
                varchar hn FK "universal"
                varchar fname
                timestamp regdate
            }
        """
        catalog = parse_mermaid_er(content)

        assert "PT" in catalog.tables
        table = catalog.tables["PT"]
        assert "hn" in table.columns
        assert "fname" in table.columns
        assert "regdate" in table.columns

    def test_parse_column_types(self):
        """Parse different column types."""
        content = """
        erDiagram
            TEST {
                varchar col1 PK
                numeric col2 FK
                timestamp col3
                int4 col4
            }
        """
        catalog = parse_mermaid_er(content)

        table = catalog.tables["TEST"]
        assert table.columns["col1"].data_type == "varchar"
        assert table.columns["col1"].is_pk
        assert table.columns["col2"].is_fk
        assert table.columns["col3"].data_type == "timestamp"

    def test_parse_additional_columns(self):
        """Parse 'more columns' indicator."""
        content = """
        erDiagram
            PT {
                varchar hn FK
                %% +8 more
            }
        """
        catalog = parse_mermaid_er(content)

        table = catalog.tables["PT"]
        assert table.additional_columns == 8

    def test_parse_solid_relationship(self):
        """Parse high-confidence solid line relationship."""
        content = """
        erDiagram
            OVST {
                varchar hn FK
            }
            PT {
                varchar hn PK
            }
            OVST }o--|| PT : "hn"
        """
        catalog = parse_mermaid_er(content)

        assert len(catalog.relationships) == 1
        rel = catalog.relationships[0]
        assert rel.from_table == "OVST"
        assert rel.to_table == "PT"
        assert rel.join_key == "hn"
        assert rel.confidence == "high"

    def test_parse_dotted_relationship(self):
        """Parse medium-confidence dotted line relationship."""
        content = """
        erDiagram
            DLVSTDT }o..|| DLVST : "dlvstreqno"
        """
        catalog = parse_mermaid_er(content)

        assert len(catalog.relationships) == 1
        rel = catalog.relationships[0]
        assert rel.confidence == "medium"

    def test_parse_many_to_many(self):
        """Parse many-to-many relationship."""
        content = """
        erDiagram
            IPT }o--o{ PT : "an,hn,vn"
        """
        catalog = parse_mermaid_er(content)

        # Should create multiple relationships for comma-separated keys
        assert len(catalog.relationships) == 3
        keys = {r.join_key for r in catalog.relationships}
        assert keys == {"an", "hn", "vn"}

    def test_table_name_uppercase(self):
        """Table names must start with uppercase in the diagram."""
        content = """
        erDiagram
            OVST {
                varchar vn
            }
        """
        catalog = parse_mermaid_er(content)

        assert "OVST" in catalog.tables
        # Table names are normalized to uppercase
        assert "ovst" not in catalog.tables

    def test_column_name_lowercase(self):
        """Column names should be lowercase."""
        content = """
        erDiagram
            PT {
                varchar HN
                varchar FName
            }
        """
        catalog = parse_mermaid_er(content)

        table = catalog.tables["PT"]
        assert "hn" in table.columns
        assert "fname" in table.columns


class TestPHIDetection:
    """Test PHI column detection."""

    def test_explicit_phi_columns(self):
        """Known PHI columns should be detected."""
        phi_cols = ["hn", "cid", "fname", "lname", "phone", "address", "dob"]
        for col in phi_cols:
            assert is_phi_column(col), f"{col} should be PHI"

    def test_non_phi_columns(self):
        """Non-PHI columns should not be flagged."""
        safe_cols = ["vn", "an", "vstdate", "cliniclct", "count", "total"]
        for col in safe_cols:
            assert not is_phi_column(col), f"{col} should not be PHI"

    def test_phi_detection_case_insensitive(self):
        """PHI detection should be case insensitive."""
        assert is_phi_column("HN")
        assert is_phi_column("Hn")
        assert is_phi_column("FNAME")

    def test_phi_columns_in_catalog(self):
        """PHI columns should be marked in catalog."""
        content = """
        erDiagram
            PT {
                varchar hn FK
                varchar fname
                timestamp vstdate
            }
        """
        catalog = parse_mermaid_er(content)

        table = catalog.tables["PT"]
        assert table.columns["hn"].is_phi
        assert table.columns["fname"].is_phi
        assert not table.columns["vstdate"].is_phi

    def test_phi_columns_collected(self):
        """PHI columns should be collected in catalog."""
        content = """
        erDiagram
            PT {
                varchar hn FK
                varchar fname
                varchar lname
            }
        """
        catalog = parse_mermaid_er(content)

        assert "hn" in catalog.phi_columns
        assert "fname" in catalog.phi_columns
        assert "lname" in catalog.phi_columns


class TestCatalogSerialization:
    """Test catalog to/from dict conversion."""

    def test_to_dict(self):
        """Catalog should serialize to dict."""
        catalog = Catalog()
        catalog.tables["PT"] = Table(
            name="PT",
            columns={
                "hn": Column(name="hn", data_type="varchar", is_fk=True, is_phi=True),
                "vstdate": Column(name="vstdate", data_type="timestamp"),
            },
        )
        catalog.relationships.append(
            Relationship(
                from_table="OVST",
                to_table="PT",
                join_key="hn",
                confidence="high",
            )
        )
        catalog.phi_columns.add("hn")

        data = catalog.to_dict()

        assert "tables" in data
        assert "PT" in data["tables"]
        assert "relationships" in data
        assert len(data["relationships"]) == 1
        assert "phi_columns" in data
        assert "hn" in data["phi_columns"]

    def test_from_dict(self):
        """Catalog should deserialize from dict."""
        data = {
            "tables": {
                "PT": {
                    "name": "PT",
                    "columns": {
                        "hn": {
                            "name": "hn",
                            "data_type": "varchar",
                            "is_pk": False,
                            "is_fk": True,
                            "fk_note": "universal",
                            "is_phi": True,
                        }
                    },
                    "additional_columns": 5,
                }
            },
            "relationships": [
                {
                    "from_table": "OVST",
                    "to_table": "PT",
                    "join_key": "hn",
                    "confidence": "high",
                }
            ],
            "phi_columns": ["hn"],
        }

        catalog = Catalog.from_dict(data)

        assert "PT" in catalog.tables
        assert catalog.tables["PT"].additional_columns == 5
        assert len(catalog.relationships) == 1
        assert "hn" in catalog.phi_columns

    def test_roundtrip(self):
        """Catalog should survive roundtrip conversion."""
        content = """
        erDiagram
            PT {
                varchar hn FK "universal"
                varchar fname
                %% +5 more
            }
            OVST }o--|| PT : "hn"
        """
        original = parse_mermaid_er(content)

        data = original.to_dict()
        restored = Catalog.from_dict(data)

        assert len(restored.tables) == len(original.tables)
        assert len(restored.relationships) == len(original.relationships)
        assert restored.phi_columns == original.phi_columns


class TestRealWorldParsing:
    """Test parsing of real-world ER diagram patterns."""

    def test_parse_multiple_tables(self):
        """Parse multiple tables at once."""
        content = """
        erDiagram
            PT {
                varchar hn FK "universal"
            }
            OVST {
                varchar hn FK "universal"
                numeric vn FK "universal"
            }
            IPT {
                varchar an FK "universal"
                varchar hn FK "universal"
            }
        """
        catalog = parse_mermaid_er(content)

        assert len(catalog.tables) == 3
        assert "PT" in catalog.tables
        assert "OVST" in catalog.tables
        assert "IPT" in catalog.tables

    def test_skip_comment_tables(self):
        """Tables that are just comments should be handled."""
        content = """
        erDiagram
            MED {
                int tables "11"
                %% MEDFORM
                %% MEDGENERIC
            }
        """
        catalog = parse_mermaid_er(content)

        # The 'tables' column should be skipped as it's metadata
        table = catalog.tables["MED"]
        assert "tables" not in table.columns


class TestFamilyInference:
    """Test table family inference."""

    def test_infer_known_prefixes(self):
        """Known prefixes should be inferred correctly."""
        assert infer_family("IPT") == "IPT"
        assert infer_family("IPTINFANTMOTHER") == "IPT"
        assert infer_family("IPTSUMDIAG") == "IPT"
        assert infer_family("OVST") == "OVST"
        assert infer_family("OVSTDISCHANGE") == "OVST"
        assert infer_family("PTDIAG") == "PT"
        assert infer_family("EYESCREENDIAG") == "EYESCREEN"

    def test_infer_from_comment(self):
        """Family should be inferred from comment markers."""
        content = """
        erDiagram
            %% ===== IPT Family =====
            IPT {
                varchar an FK
            }
            IPTSUMDCT {
                varchar an FK
            }
        """
        catalog = parse_mermaid_er(content)

        assert catalog.tables["IPT"].family == "IPT"
        assert catalog.tables["IPTSUMDCT"].family == "IPT"

    def test_family_assigned_to_table(self):
        """Tables should have family assigned."""
        content = """
        erDiagram
            OVST {
                varchar vn FK
            }
        """
        catalog = parse_mermaid_er(content)

        assert catalog.tables["OVST"].family == "OVST"


class TestCatalogValidation:
    """Test catalog validation methods."""

    def test_table_exists(self):
        """Test table existence check."""
        catalog = Catalog()
        catalog.tables["PT"] = Table(name="PT", family="PT")

        assert catalog.table_exists("PT")
        assert catalog.table_exists("pt")  # case insensitive
        assert not catalog.table_exists("INVALID")

    def test_column_exists(self):
        """Test column existence check."""
        catalog = Catalog()
        catalog.tables["PT"] = Table(
            name="PT",
            family="PT",
            columns={"hn": Column(name="hn", data_type="varchar")}
        )

        assert catalog.column_exists("PT", "hn")
        assert not catalog.column_exists("PT", "invalid")
        assert not catalog.column_exists("INVALID", "hn")

    def test_get_phi_columns_in_table(self):
        """Test getting PHI columns for a table."""
        catalog = Catalog()
        catalog.tables["PT"] = Table(
            name="PT",
            family="PT",
            columns={
                "hn": Column(name="hn", data_type="varchar", is_phi=True),
                "fname": Column(name="fname", data_type="varchar", is_phi=True),
                "vstdate": Column(name="vstdate", data_type="timestamp", is_phi=False),
            }
        )

        phi_cols = catalog.get_phi_columns_in_table("PT")
        assert "hn" in phi_cols
        assert "fname" in phi_cols
        assert "vstdate" not in phi_cols

    def test_validate_sql_references(self):
        """Test SQL reference validation."""
        catalog = Catalog()
        catalog.tables["PT"] = Table(
            name="PT",
            family="PT",
            columns={
                "hn": Column(name="hn", data_type="varchar"),
                "vstdate": Column(name="vstdate", data_type="timestamp"),
            }
        )
        catalog.tables["OVST"] = Table(
            name="OVST",
            family="OVST",
            columns={
                "vn": Column(name="vn", data_type="numeric"),
            }
        )

        # Valid references
        invalid_tables, invalid_cols = catalog.validate_sql_references(
            tables=["PT", "OVST"],
            columns={"PT": ["hn", "vstdate"], "OVST": ["vn"]}
        )
        assert invalid_tables == []
        assert invalid_cols == []

        # Invalid table
        invalid_tables, invalid_cols = catalog.validate_sql_references(
            tables=["PT", "INVALID"],
            columns={"PT": ["hn"]}
        )
        assert "INVALID" in invalid_tables

        # Invalid column
        invalid_tables, invalid_cols = catalog.validate_sql_references(
            tables=["PT"],
            columns={"PT": ["hn", "badcol"]}
        )
        assert "PT.badcol" in invalid_cols

    def test_find_join_paths(self):
        """Test finding join paths between tables."""
        catalog = Catalog()
        catalog.relationships = [
            Relationship(from_table="OVST", to_table="PT", join_key="hn", confidence="high"),
            Relationship(from_table="IPT", to_table="PT", join_key="hn", confidence="high"),
        ]

        paths = catalog.find_join_paths("OVST", "PT")
        assert len(paths) == 1
        assert paths[0].join_key == "hn"

        # Should work in reverse direction too
        paths = catalog.find_join_paths("PT", "OVST")
        assert len(paths) == 1


class TestCatalogFamilies:
    """Test catalog family-related functionality."""

    def test_get_family_tables(self):
        """Test getting tables by family."""
        catalog = Catalog()
        catalog.families = {
            "IPT": ["IPT", "IPTSUMDCT", "IPTSUMDIAG"],
            "PT": ["PT", "PTDIAG"],
        }

        ipt_tables = catalog.get_family_tables("IPT")
        assert len(ipt_tables) == 3
        assert "IPTSUMDCT" in ipt_tables

        # Case insensitive lookup
        assert catalog.get_family_tables("ipt") == ["IPT", "IPTSUMDCT", "IPTSUMDIAG"]

    def test_families_in_serialization(self):
        """Families should be included in serialization."""
        catalog = Catalog()
        catalog.tables["IPT"] = Table(name="IPT", family="IPT")
        catalog.families = {"IPT": ["IPT"]}

        data = catalog.to_dict()
        assert "families" in data
        assert "IPT" in data["families"]

        restored = Catalog.from_dict(data)
        assert "IPT" in restored.families
