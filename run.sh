#!/bin/bash
set -e

# KCMH SQL Bot Startup Script

# Check if .env exists
if [ ! -f .env ]; then
    echo "Error: .env file not found. Copy .env.example to .env and configure it."
    exit 1
fi

# Generate schema knowledge if missing or stale (any source CSV newer than the cache)
schema_json="out/schema_knowledge.json"
schema_sources=(
    schema/frequent_table.csv
    schema/frequent_column_enriched.csv
    schema/join_edges.csv
)

needs_regen=0
if [ ! -f "$schema_json" ]; then
    needs_regen=1
else
    for src in "${schema_sources[@]}"; do
        if [ -f "$src" ] && [ "$src" -nt "$schema_json" ]; then
            needs_regen=1
            echo "Schema source '$src' is newer than $schema_json — regenerating."
            break
        fi
    done
fi

if [ "$needs_regen" -eq 1 ]; then
    echo "Generating schema knowledge from CSV files..."
    uv run python -c "from app.schema_parser import generate_schema_knowledge; generate_schema_knowledge()"
fi

# Start the server
echo "Starting KCMH SQL Bot..."
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
