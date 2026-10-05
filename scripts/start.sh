#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v uv &>/dev/null; then
    echo "Error: uv is not installed. Please install uv (https://docs.astral.sh/uv/)."
    exit 1
fi

if [ ! -f ".env" ]; then
    echo "Creating .env from .env.example. Add your OPENROUTER_API_KEY to it."
    cp .env.example .env
fi

PORT="${PORT:-8501}"
uv sync --locked
echo "Starting Text-to-SQL on http://localhost:$PORT"
exec uv run streamlit run app.py --server.port "$PORT" --server.headless true
