#!/bin/bash
set -e

# KCMH SQL Bot Startup Script

# Check if .env exists
if [ ! -f .env ]; then
    echo "Error: .env file not found. Copy .env.example to .env and configure it."
    exit 1
fi

# Generate catalog if not exists
if [ ! -f out/catalog.json ]; then
    echo "Generating catalog from ER diagrams..."
    uv run python -c "from app.catalog import generate_catalog; generate_catalog()"
fi

# Start the server
echo "Starting KCMH SQL Bot..."
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
