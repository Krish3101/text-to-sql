"""Builds the SQLite database from data/schema.sql and data/seed.sql."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from text_to_sql.config import DEFAULT_DB_PATH, SCHEMA_PATH, SEED_PATH, SEED_VERSION
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


def init_db(db_path: str | Path = DEFAULT_DB_PATH, force: bool = False) -> str:
    """
    Initializes and seeds the database from data/schema.sql and data/seed.sql.
    Uses atomic file replacement to ensure database consistency.
    """
    resolved = Path(db_path).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)

    if resolved.exists() and not force:
        try:
            with closing(sqlite3.connect(str(resolved), timeout=5.0)) as conn:
                ver = conn.execute("PRAGMA user_version;").fetchone()[0]
                count = conn.execute("SELECT COUNT(*) FROM customers;").fetchone()[0]
            if ver == SEED_VERSION and count > 0:
                return str(resolved)
        except Exception:
            pass  # Rebuild if verification fails

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

        conn.execute(f"PRAGMA user_version = {SEED_VERSION};")
        conn.commit()
    finally:
        conn.close()

    os.replace(temp_path, resolved)
    return str(resolved)
