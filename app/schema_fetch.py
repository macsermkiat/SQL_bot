"""
DEPRECATED: This module uses the old catalog.json system.

The application now uses CSV-based schema files:
- schema/frequent_table.csv
- schema/frequent_column_enriched.csv
- schema/join_edges.csv

These are parsed by app.schema_parser into out/schema_knowledge.json.

This file is kept for reference but should not be used for new development.
To update schema, edit the CSV files and run:
    uv run python -c "from app.schema_parser import generate_schema_knowledge; generate_schema_knowledge()"
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg

from app.catalog import Catalog, Table, Column, PHI_COLUMNS, is_phi_column
from app.config import get_settings


def fetch_schema_from_db(connection_url: str) -> Catalog:
    """
    Fetch complete schema from PostgreSQL database.

    Args:
        connection_url: PostgreSQL connection URL

    Returns:
        Catalog with all tables and columns
    """
    catalog = Catalog()

    with psycopg.connect(connection_url) as conn:
        with conn.cursor() as cur:
            # Get all tables from KCMH_HIS schema
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'KCMH_HIS'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)
            tables = [row[0] for row in cur.fetchall()]

            print(f"Found {len(tables)} tables")

            # Get columns for each table
            for table_name in tables:
                cur.execute("""
                    SELECT
                        column_name,
                        data_type,
                        is_nullable,
                        column_default
                    FROM information_schema.columns
                    WHERE table_schema = 'KCMH_HIS'
                      AND table_name = %s
                    ORDER BY ordinal_position
                """, (table_name,))

                columns = cur.fetchall()

                table = Table(name=table_name.upper())

                for col_name, data_type, is_nullable, col_default in columns:
                    col_name_lower = col_name.lower()

                    # Detect primary key
                    is_pk = col_default and 'nextval' in str(col_default)

                    # Detect foreign key (common patterns)
                    is_fk = col_name_lower in ('hn', 'an', 'vn') or col_name_lower.endswith('_id')

                    column = Column(
                        name=col_name_lower,
                        data_type=data_type,
                        is_pk=is_pk,
                        is_fk=is_fk,
                        is_phi=is_phi_column(col_name_lower),
                    )
                    table.columns[col_name_lower] = column

                    if column.is_phi:
                        catalog.phi_columns.add(col_name_lower)

                catalog.tables[table_name.upper()] = table
                print(f"  {table_name}: {len(columns)} columns")

    return catalog


def merge_catalogs(existing: Catalog, fetched: Catalog) -> Catalog:
    """
    Merge fetched catalog with existing (preserve relationships from ER diagrams).

    Args:
        existing: Existing catalog (from ER diagrams)
        fetched: Freshly fetched catalog (from database)

    Returns:
        Merged catalog
    """
    # Start with fetched (complete column info)
    merged = fetched

    # Copy relationships from existing
    merged.relationships = existing.relationships.copy()

    # Merge PHI columns
    merged.phi_columns.update(existing.phi_columns)

    return merged


def generate_mermaid_er(catalog: Catalog, output_path: Path) -> None:
    """
    Generate expanded Mermaid ER diagram from catalog.

    Args:
        catalog: Catalog to convert
        output_path: Output file path
    """
    lines = [
        "%% Hospital Information System - Complete ER Diagram",
        "%% Auto-generated from database schema",
        "%% WARNING: This file is large - auto-generated from database schema",
        "",
        "erDiagram",
        "",
    ]

    # Group tables by prefix
    table_groups: dict[str, list[str]] = {}
    for table_name in sorted(catalog.tables.keys()):
        # Extract prefix (first word or up to first underscore)
        prefix = table_name.split('_')[0][:6]
        if prefix not in table_groups:
            table_groups[prefix] = []
        table_groups[prefix].append(table_name)

    # Generate table definitions
    for prefix in sorted(table_groups.keys()):
        lines.append(f"    %% ===== {prefix} Family =====")

        for table_name in table_groups[prefix]:
            table = catalog.tables[table_name]
            lines.append(f"    {table_name} {{")

            for col_name, col in table.columns.items():
                pk_marker = " PK" if col.is_pk else ""
                fk_marker = " FK" if col.is_fk else ""
                phi_marker = ' "PHI"' if col.is_phi else ""
                lines.append(f"        {col.data_type} {col_name}{pk_marker}{fk_marker}{phi_marker}")

            lines.append("    }")

        lines.append("")

    # Add relationships
    if catalog.relationships:
        lines.append("    %% ===== Relationships =====")
        for rel in catalog.relationships:
            connector = "}o--||" if rel.confidence == "high" else "}o..||"
            lines.append(f'    {rel.from_table} {connector} {rel.to_table} : "{rel.join_key}"')

    output_path.write_text("\n".join(lines))
    print(f"Generated Mermaid ER diagram: {output_path}")


def main():
    """Main entry point."""
    settings = get_settings()
    base_dir = settings.base_dir

    print("Fetching schema from database...")
    print(f"Connection: {settings.db_url[:50]}...")

    try:
        fetched_catalog = fetch_schema_from_db(settings.db_url)
    except Exception as e:
        print(f"Error connecting to database: {e}")
        print("\nMake sure you're connected to the hospital network or VPN.")
        return

    # Load existing catalog (for relationships)
    existing_catalog_path = base_dir / "out" / "catalog.json"
    if existing_catalog_path.exists():
        print("\nMerging with existing catalog (preserving relationships)...")
        with open(existing_catalog_path) as f:
            existing = Catalog.from_dict(json.load(f))
        merged = merge_catalogs(existing, fetched_catalog)
    else:
        merged = fetched_catalog

    # Save updated catalog
    output_path = base_dir / "out" / "catalog.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(merged.to_dict(), f, indent=2)

    print(f"\nSaved catalog: {output_path}")
    print(f"  Tables: {len(merged.tables)}")
    print(f"  Total columns: {sum(len(t.columns) for t in merged.tables.values())}")
    print(f"  Relationships: {len(merged.relationships)}")
    print(f"  PHI columns: {len(merged.phi_columns)}")

    # Generate expanded Mermaid diagram
    mermaid_path = base_dir / "schema" / "schema_complete.mmd"
    generate_mermaid_er(merged, mermaid_path)

    print("\nDone! Restart the server to use the updated catalog.")


if __name__ == "__main__":
    main()
