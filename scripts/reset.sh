#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Resetting Text-to-SQL"

# The database is seeded deterministically, so removing it costs nothing.
rm -f ecommerce.db
echo "Database removed (reseeded on next start)"

rm -rf .venv
echo "Virtual environment removed"

rm -rf .pytest_cache .ruff_cache
find . -type d -name __pycache__ -not -path "./.venv/*" -prune -exec rm -rf {} + 2>/dev/null || true
echo "Caches cleaned"

echo "Reset complete. Run ./scripts/start.sh to launch."
