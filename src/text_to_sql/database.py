"""Builds the SQLite database from data/schema.sql and data/seed.sql."""

import os
import sqlite3
from pathlib import Path

from text_to_sql.config import DEFAULT_DB_PATH, SCHEMA_PATH, SEED_PATH
from text_to_sql.executor import connect_ro
from text_to_sql.schema import TABLES


def get_database_stats(db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, int]:
    """Returns row counts for all known schema tables."""
    conn = connect_ro(db_path)
    try:
        stats = {}
        for table in TABLES:
            cur = conn.cursor()
            cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            stats[table] = cur.fetchone()[0]
            cur.close()
        return stats
    finally:
        conn.close()


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> str:
    """
    Builds the database from data/schema.sql and data/seed.sql when the file is missing.
    It is built under a temporary name and renamed, so a half-built file never appears.
    """
    resolved = Path(db_path).resolve()
    if resolved.exists():
        return str(resolved)
    resolved.parent.mkdir(parents=True, exist_ok=True)

    temp_path = resolved.with_suffix(".tmp")
    if temp_path.exists():
        temp_path.unlink()

    conn = sqlite3.connect(str(temp_path), timeout=10.0)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")

        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema_sql)

        seed_sql = SEED_PATH.read_text(encoding="utf-8")
        conn.executescript(seed_sql)

        # Integrity verification
        fk_errors = conn.execute("PRAGMA foreign_key_check;").fetchall()
        if fk_errors:
            raise RuntimeError(f"Foreign key check failed: {fk_errors}")

        integrity = conn.execute("PRAGMA integrity_check;").fetchall()
        if integrity != [("ok",)]:
            raise RuntimeError(f"Integrity check failed: {integrity}")

        conn.commit()
    finally:
        conn.close()

    os.replace(temp_path, resolved)
    return str(resolved)
