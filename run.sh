#!/bin/bash
set -e

# KCMH SQL Bot Startup Script

# Check if .env exists
if [ ! -f .env ]; then
    echo "Error: .env file not found. Copy .env.example to .env and configure it."
    exit 1
fi

# Generate schema knowledge if not exists
if [ ! -f out/schema_knowledge.json ]; then
    echo "Generating schema knowledge from CSV files..."
    uv run python -c "from app.schema_parser import generate_schema_knowledge; generate_schema_knowledge()"
fi

# Start the server
echo "Starting KCMH SQL Bot..."
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
