"""Constants used across the app."""

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent.parent
DATA_DIR = PACKAGE_DIR / "data"

SCHEMA_PATH = DATA_DIR / "schema.sql"
SEED_PATH = DATA_DIR / "seed.sql"

DEFAULT_DB_PATH = PROJECT_ROOT / "ecommerce.db"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
AS_OF_DATE = "2026-02-28"
MAX_ROWS = 1000
MAX_RESULT_BYTES = 10_000_000  # 10 MB total result payload cap
MAX_CELL_BYTES = 1_000_000  # 1 MB max single string or blob
MAX_SQL_BYTES = 20_000  # 20 KB max SQL query size
QUERY_TIMEOUT_S = 3.0
MAX_RETRIES = 1


def get_model() -> str:
    """OPENROUTER_MODEL if set and not blank, else DEFAULT_MODEL. Read at call time, after load_dotenv."""
    return os.environ.get("OPENROUTER_MODEL", "").strip() or DEFAULT_MODEL
