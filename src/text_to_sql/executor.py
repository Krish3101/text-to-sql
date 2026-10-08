"""Runs a checked query on a read-only connection, with a deadline and a row cap."""

import sqlite3
import time
from pathlib import Path
from typing import Any

from text_to_sql.config import DEFAULT_DB_PATH, MAX_ROWS, QUERY_TIMEOUT_S


def connect_ro(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Opens the database file read-only, so SQLite itself refuses any write."""
    resolved = Path(db_path).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Database file does not exist at {resolved}. Run init_db() first.")
    return sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True, timeout=5.0)


def run_query(
    sql: str,
    db_path: str | Path = DEFAULT_DB_PATH,
    timeout_s: float = QUERY_TIMEOUT_S,
    max_rows: int = MAX_ROWS,
) -> tuple[list[str], list[tuple[Any, ...]], bool]:
    """Returns (columns, rows, truncated). Raises sqlite3.OperationalError on a timeout."""
    conn = connect_ro(db_path)
    try:
        deadline = time.monotonic() + timeout_s
        # A non-zero return interrupts the query, so a runaway recursive CTE stops at the deadline.
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
        cursor = conn.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(max_rows + 1)
        return columns, rows[:max_rows], len(rows) > max_rows
    finally:
        conn.close()
