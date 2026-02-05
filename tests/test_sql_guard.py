"""
Tests for SQL Guard - CRITICAL safety validation.

These tests ensure the SQL guard properly blocks:
- Non-SELECT statements
- PHI columns in SELECT output
- SELECT *
- Missing LIMIT on non-aggregate queries
- Forbidden keywords
"""

import pytest
from app.sql_guard import (
    validate_sql,
    guard_sql,
    ForbiddenKeywordError,
    ForbiddenStatementError,
    PHIExposureError,
    SelectStarError,
    MissingLimitError,
    SQLParseError,
)


class TestStatementTypeValidation:
    """Test that only SELECT statements are allowed."""

    def test_select_allowed(self):
        """Simple SELECT should pass."""
        result = validate_sql("SELECT COUNT(*) FROM ovst")
        assert result.valid

    def test_select_with_cte_allowed(self):
        """SELECT with CTE should pass."""
        sql = """
        WITH visits AS (
            SELECT vn, vstdate FROM ovst WHERE vstdate >= '2024-01-01'
        )
        SELECT COUNT(*) FROM visits
        """
        result = validate_sql(sql)
        assert result.valid

    def test_insert_blocked(self):
        """INSERT should be blocked."""
        result = validate_sql("INSERT INTO ovst (vn) VALUES (1)")
        assert not result.valid
        assert "INSERT" in result.error

    def test_update_blocked(self):
        """UPDATE should be blocked."""
        result = validate_sql("UPDATE ovst SET vstdate = '2024-01-01'")
        assert not result.valid
        assert "UPDATE" in result.error

    def test_delete_blocked(self):
        """DELETE should be blocked."""
        result = validate_sql("DELETE FROM ovst WHERE vn = 1")
        assert not result.valid
        assert "DELETE" in result.error

    def test_drop_blocked(self):
        """DROP should be blocked."""
        result = validate_sql("DROP TABLE ovst")
        assert not result.valid
        assert "DROP" in result.error

    def test_truncate_blocked(self):
        """TRUNCATE should be blocked."""
        result = validate_sql("TRUNCATE TABLE ovst")
        assert not result.valid
        assert "TRUNCATE" in result.error

    def test_create_blocked(self):
        """CREATE should be blocked."""
        result = validate_sql("CREATE TABLE test (id INT)")
        assert not result.valid
        assert "CREATE" in result.error

    def test_alter_blocked(self):
        """ALTER should be blocked."""
        result = validate_sql("ALTER TABLE ovst ADD COLUMN test INT")
        assert not result.valid
        assert "ALTER" in result.error

    def test_grant_blocked(self):
        """GRANT should be blocked."""
        result = validate_sql("GRANT SELECT ON ovst TO public")
        assert not result.valid
        assert "GRANT" in result.error


class TestPHIBlocking:
    """Test that PHI columns are blocked in SELECT output."""

    def test_hn_in_select_blocked(self):
        """HN (hospital number) in SELECT should be blocked."""
        result = validate_sql("SELECT hn, COUNT(*) FROM ovst GROUP BY hn LIMIT 10")
        assert not result.valid
        assert "PHI" in result.error or "hn" in result.error.lower()

    def test_name_in_select_blocked(self):
        """Name columns in SELECT should be blocked."""
        result = validate_sql("SELECT fname, lname FROM pt LIMIT 10")
        assert not result.valid
        assert "PHI" in result.error

    def test_phone_in_select_blocked(self):
        """Phone in SELECT should be blocked."""
        result = validate_sql("SELECT phone FROM pt LIMIT 10")
        assert not result.valid
        assert "PHI" in result.error

    def test_dob_in_select_blocked(self):
        """Date of birth in SELECT should be blocked."""
        result = validate_sql("SELECT dob FROM pt LIMIT 10")
        assert not result.valid
        assert "PHI" in result.error

    def test_address_in_select_blocked(self):
        """Address in SELECT should be blocked."""
        result = validate_sql("SELECT address FROM pt LIMIT 10")
        assert not result.valid
        assert "PHI" in result.error

    def test_hn_in_where_allowed(self):
        """HN in WHERE clause should be allowed (for joins)."""
        result = validate_sql(
            "SELECT COUNT(*) FROM ovst WHERE hn = '12345'"
        )
        assert result.valid

    def test_hn_in_join_allowed(self):
        """HN in JOIN should be allowed."""
        result = validate_sql("""
            SELECT COUNT(*)
            FROM ovst o
            JOIN pt p ON o.hn = p.hn
            WHERE o.vstdate >= '2024-01-01'
        """)
        assert result.valid


class TestSelectStarBlocking:
    """Test that SELECT * is blocked."""

    def test_select_star_blocked(self):
        """SELECT * should be blocked."""
        result = validate_sql("SELECT * FROM ovst LIMIT 10")
        assert not result.valid
        assert "SELECT *" in result.error

    def test_select_table_star_blocked(self):
        """SELECT table.* should be blocked."""
        result = validate_sql("SELECT o.* FROM ovst o LIMIT 10")
        assert not result.valid
        assert "SELECT" in result.error and "*" in result.error

    def test_explicit_columns_allowed(self):
        """Explicit column names should be allowed."""
        result = validate_sql("SELECT vn, vstdate FROM ovst LIMIT 10")
        assert result.valid


class TestLimitEnforcement:
    """Test LIMIT enforcement for non-aggregate queries."""

    def test_aggregate_without_limit_allowed(self):
        """Aggregate query without LIMIT should pass."""
        result = validate_sql("SELECT COUNT(*) FROM ovst")
        assert result.valid

    def test_group_by_without_limit_allowed(self):
        """Query with GROUP BY without LIMIT should pass."""
        result = validate_sql("""
            SELECT vstdate, COUNT(*)
            FROM ovst
            GROUP BY vstdate
        """)
        assert result.valid

    def test_non_aggregate_without_limit_blocked(self):
        """Non-aggregate query without LIMIT should be blocked."""
        result = validate_sql("SELECT vn, vstdate FROM ovst")
        assert not result.valid
        assert "LIMIT" in result.error

    def test_non_aggregate_with_limit_allowed(self):
        """Non-aggregate query with LIMIT should pass."""
        result = validate_sql("SELECT vn, vstdate FROM ovst LIMIT 100")
        assert result.valid

    def test_limit_too_high_blocked(self):
        """LIMIT exceeding max should be blocked."""
        result = validate_sql("SELECT vn FROM ovst LIMIT 10000", max_rows=2000)
        assert not result.valid
        assert "LIMIT" in result.error

    def test_limit_at_max_allowed(self):
        """LIMIT at exactly max should pass."""
        result = validate_sql("SELECT vn FROM ovst LIMIT 2000", max_rows=2000)
        assert result.valid


class TestSQLInjectionPrevention:
    """Test that SQL injection attempts are blocked."""

    def test_semicolon_injection_blocked(self):
        """Semicolon injection should be blocked."""
        result = validate_sql("SELECT COUNT(*) FROM ovst; DROP TABLE ovst")
        assert not result.valid

    def test_comment_injection_safe(self):
        """Comments in SQL should be handled safely."""
        # This should still be valid if it's just a SELECT
        result = validate_sql("SELECT COUNT(*) FROM ovst -- comment")
        assert result.valid

    def test_union_injection_safe(self):
        """UNION should work but still be SELECT-only."""
        result = validate_sql("""
            SELECT vn FROM ovst WHERE vn = '1' LIMIT 10
            UNION
            SELECT vn FROM ovst WHERE vn = '2' LIMIT 10
        """)
        # UNION of SELECTs is allowed
        assert result.valid


class TestGuardFunction:
    """Test the guard_sql function that raises exceptions."""

    def test_guard_returns_sql_on_valid(self):
        """guard_sql should return SQL when valid."""
        sql = "SELECT COUNT(*) FROM ovst"
        result = guard_sql(sql)
        assert result == sql

    def test_guard_raises_on_insert(self):
        """guard_sql should raise ForbiddenKeywordError on INSERT."""
        with pytest.raises(ForbiddenKeywordError):
            guard_sql("INSERT INTO ovst VALUES (1)")

    def test_guard_raises_on_phi(self):
        """guard_sql should raise PHIExposureError on PHI in SELECT."""
        with pytest.raises(PHIExposureError):
            guard_sql("SELECT hn FROM ovst LIMIT 10")

    def test_guard_raises_on_select_star(self):
        """guard_sql should raise SelectStarError on SELECT *."""
        with pytest.raises(SelectStarError):
            guard_sql("SELECT * FROM ovst LIMIT 10")

    def test_guard_raises_on_missing_limit(self):
        """guard_sql should raise MissingLimitError when needed."""
        with pytest.raises(MissingLimitError):
            guard_sql("SELECT vn FROM ovst")


class TestEdgeCases:
    """Test edge cases and complex queries."""

    def test_subquery_allowed(self):
        """Subqueries in SELECT should work."""
        result = validate_sql("""
            SELECT
                (SELECT COUNT(*) FROM ovst) as total_visits
        """)
        assert result.valid

    def test_case_expression_allowed(self):
        """CASE expressions should work."""
        result = validate_sql("""
            SELECT
                CASE WHEN vstdate >= '2024-01-01' THEN 'New' ELSE 'Old' END as category,
                COUNT(*) as cnt
            FROM ovst
            GROUP BY 1
        """)
        assert result.valid

    def test_window_function_needs_limit(self):
        """Window functions without GROUP BY need LIMIT."""
        result = validate_sql("""
            SELECT
                vn,
                ROW_NUMBER() OVER (ORDER BY vstdate) as rn
            FROM ovst
        """)
        assert not result.valid  # Needs LIMIT

        result = validate_sql("""
            SELECT
                vn,
                ROW_NUMBER() OVER (ORDER BY vstdate) as rn
            FROM ovst
            LIMIT 100
        """)
        assert result.valid

    def test_distinct_as_aggregate(self):
        """DISTINCT should be treated as aggregation."""
        result = validate_sql("SELECT DISTINCT cliniclct FROM ovst")
        assert result.valid  # DISTINCT acts like aggregation

    def test_complex_join_allowed(self):
        """Complex JOINs should work."""
        # Note: Using 'prefix' instead of 'name' because 'name' is in PHI blocklist
        # (even though c.name is clinic name, not patient name - this is a known limitation)
        result = validate_sql("""
            SELECT
                c.prefix as clinic_prefix,
                COUNT(DISTINCT o.vn) as visit_count
            FROM ovst o
            JOIN cliniclct c ON o.cliniclct = c.cliniclct
            WHERE o.vstdate >= '2024-01-01'
            GROUP BY c.prefix
        """)
        assert result.valid

    def test_string_containing_keyword_allowed(self):
        """Strings containing forbidden keywords should be allowed."""
        result = validate_sql(
            "SELECT COUNT(*) FROM ovst WHERE notes LIKE '%DELETE%' "
        )
        assert result.valid


class TestValidationMetadata:
    """Test that validation returns useful metadata."""

    def test_tables_extracted(self):
        """Tables should be extracted from query."""
        result = validate_sql("""
            SELECT COUNT(*)
            FROM ovst o
            JOIN pt p ON o.hn = p.hn
        """)
        assert result.valid
        assert "OVST" in result.tables_used
        assert "PT" in result.tables_used

    def test_aggregation_detected(self):
        """Aggregation should be detected."""
        result = validate_sql("SELECT COUNT(*) FROM ovst")
        assert result.valid
        assert result.has_aggregation

        result = validate_sql("SELECT vn FROM ovst LIMIT 10")
        assert result.valid
        assert not result.has_aggregation

    def test_limit_value_extracted(self):
        """LIMIT value should be extracted."""
        result = validate_sql("SELECT vn FROM ovst LIMIT 100")
        assert result.valid
        assert result.has_limit
        assert result.limit_value == 100


class TestCatalogIntegration:
    """Test catalog integration for schema grounding."""

    @pytest.fixture
    def mock_catalog(self):
        """Create a mock catalog for testing."""
        from app.catalog import Catalog, Table, Column

        catalog = Catalog()
        catalog.tables["OVST"] = Table(
            name="OVST",
            family="OVST",
            columns={
                "vn": Column(name="vn", data_type="numeric", is_fk=True),
                "hn": Column(name="hn", data_type="varchar", is_fk=True, is_phi=True),
                "vstdate": Column(name="vstdate", data_type="timestamp"),
                "cliniclct": Column(name="cliniclct", data_type="numeric"),
            }
        )
        catalog.tables["PT"] = Table(
            name="PT",
            family="PT",
            columns={
                "hn": Column(name="hn", data_type="varchar", is_pk=True, is_phi=True),
                "fname": Column(name="fname", data_type="varchar", is_phi=True),
                "lname": Column(name="lname", data_type="varchar", is_phi=True),
                "birthdate": Column(name="birthdate", data_type="date", is_phi=True),
            }
        )
        catalog.families = {
            "OVST": ["OVST"],
            "PT": ["PT"],
        }
        return catalog

    def test_valid_table_with_catalog(self, mock_catalog):
        """Valid table should pass with catalog validation."""
        result = validate_sql(
            "SELECT COUNT(*) FROM ovst",
            catalog=mock_catalog,
            strict_catalog_check=True,
        )
        assert result.valid

    def test_unknown_table_blocked_strict(self, mock_catalog):
        """Unknown table should be blocked in strict mode."""
        result = validate_sql(
            "SELECT COUNT(*) FROM unknown_table",
            catalog=mock_catalog,
            strict_catalog_check=True,
        )
        assert not result.valid
        assert "Unknown table" in result.error

    def test_unknown_table_warning_nonstrict(self, mock_catalog):
        """Unknown table should produce warning in non-strict mode."""
        result = validate_sql(
            "SELECT COUNT(*) FROM unknown_table",
            catalog=mock_catalog,
            strict_catalog_check=False,
        )
        assert result.valid
        assert any("unknown_table" in w.lower() for w in result.warnings)

    def test_unknown_column_blocked_strict(self, mock_catalog):
        """Unknown column should be blocked in strict mode when table-qualified."""
        # Use table alias to ensure column is associated with the table
        result = validate_sql(
            "SELECT o.nonexistent_col FROM ovst o LIMIT 10",
            catalog=mock_catalog,
            strict_catalog_check=True,
        )
        assert not result.valid
        assert "Unknown column" in result.error

    def test_valid_columns_pass_strict(self, mock_catalog):
        """Valid columns should pass in strict mode."""
        result = validate_sql(
            "SELECT vn, vstdate FROM ovst LIMIT 10",
            catalog=mock_catalog,
            strict_catalog_check=True,
        )
        assert result.valid

    def test_phi_from_catalog_blocked(self, mock_catalog):
        """PHI columns marked in catalog should be blocked."""
        # fname is marked as PHI in the catalog
        result = validate_sql(
            "SELECT fname FROM pt LIMIT 10",
            catalog=mock_catalog,
        )
        assert not result.valid
        assert "PHI" in result.error

    def test_join_with_catalog_validation(self, mock_catalog):
        """JOINs should validate both tables against catalog."""
        result = validate_sql(
            """
            SELECT COUNT(*)
            FROM ovst o
            JOIN pt p ON o.hn = p.hn
            WHERE o.vstdate >= '2024-01-01'
            """,
            catalog=mock_catalog,
            strict_catalog_check=True,
        )
        assert result.valid

    def test_all_columns_extracted(self, mock_catalog):
        """All columns (not just SELECT) should be extracted."""
        # Use table alias to ensure columns are associated with the table
        result = validate_sql(
            """
            SELECT o.vn, o.vstdate
            FROM ovst o
            WHERE o.cliniclct = 1
            ORDER BY o.vstdate
            LIMIT 10
            """,
            catalog=mock_catalog,
        )
        assert result.valid
        # all_columns should include columns from WHERE and ORDER BY
        assert result.all_columns is not None
        # Aliases are resolved to actual table names
        ovst_cols = result.all_columns.get("OVST", [])
        assert "cliniclct" in ovst_cols
        assert "vstdate" in ovst_cols
        assert "vn" in ovst_cols


class TestConvenienceFunctions:
    """Test convenience functions for catalog integration."""

    def test_validate_with_catalog_imports(self):
        """validate_with_catalog should work with default catalog."""
        from app.sql_guard import validate_with_catalog

        # This should work even if the catalog has limited tables
        result = validate_with_catalog(
            "SELECT COUNT(*) FROM ipt",
            strict=False,  # Non-strict since we may not have all tables
        )
        assert result.valid

    def test_guard_with_catalog_imports(self):
        """guard_with_catalog should work with default catalog."""
        from app.sql_guard import guard_with_catalog

        # This should work for valid queries
        sql = "SELECT COUNT(*) FROM ipt"
        result = guard_with_catalog(sql, strict=False)
        assert result == sql
