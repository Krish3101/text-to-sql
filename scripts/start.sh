#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v python3 &>/dev/null; then
    echo "Error: python3 is not installed or not in PATH."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment in .venv..."
    python3 -m venv .venv
    echo "Installing dependencies..."
    .venv/bin/pip install --quiet --upgrade pip
    .venv/bin/pip install --quiet -r requirements.txt
fi

if [ ! -f ".env" ]; then
    echo "Creating .env from .env.example. Add your OPENROUTER_API_KEY to it."
    cp .env.example .env
fi

echo "Starting Text-to-SQL on http://localhost:8501"
exec .venv/bin/streamlit run app.py
