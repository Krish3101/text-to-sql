"""Read-only SQLite query executor with defense-in-depth security.

Enforces:
1. URI mode=ro read-only connection.
2. PRAGMA query_only = ON.
3. Resource limits via setlimit:
   - SQLITE_LIMIT_ATTACHED = 0 (blocks ATTACH from creating any files)
   - SQLITE_LIMIT_LENGTH = 1_000_000 (blocks 2GB memory allocation via randomblob/zeroblob)
   - SQLITE_LIMIT_SQL_LENGTH = 20_000
4. SQLite Authorizer (set_authorizer) installed after configuration:
   - Allows only SELECT, RECURSIVE, safe functions, and READs from known schema tables.
   - Denies ATTACH, DETACH, PRAGMA, writes, DDL, VACUUM, and sqlite_master access.
5. Wall-clock execution deadline (3.0 seconds default).
6. Result row cap (1,000 rows default) with 'truncated' flag.
"""

import functools
import sqlite3
import time
from pathlib import Path
from typing import Any

from text_to_sql.config import (
    DEFAULT_DB_PATH,
    MAX_CELL_BYTES,
    MAX_ROWS,
    MAX_SQL_BYTES,
    QUERY_TIMEOUT_S,
)
from text_to_sql.guardrails import ALLOWED_FUNCTIONS
from text_to_sql.schema import KNOWN_TABLES

# Table-valued functions that SQLite builds can query without CREATE (pragma_* is matched by prefix).
TABLE_FUNCTIONS = frozenset(
    {"json_each", "json_tree", "jsonb_each", "jsonb_tree", "dbstat", "generate_series", "carray"}
)


def _security_authorizer(
    action_code: int,
    arg1: Any,
    arg2: Any,
    dbname: Any,
    source: Any,
    physical_tables: frozenset[str] = frozenset(),
) -> int:
    """
    SQLite authorizer callback for read-only isolation.
    Only permits SELECT, RECURSIVE queries, authorized scalar functions,
    and reading from known application schema tables.
    physical_tables is every table/view in the database; connect_ro fills it in.
    """
    if action_code in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK

    if action_code == sqlite3.SQLITE_READ:
        tbl = str(arg1).lower() if arg1 else ""
        if dbname:
            if str(dbname).lower() == "main" and tbl in KNOWN_TABLES:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        # No database name: SQLite's table-level check when no column is read (COUNT(*), SELECT 1).
        # It also fires for CTE names, so deny by name: SQLite's own tables, the table-valued
        # functions, and real tables that are not in KNOWN_TABLES.
        if tbl.startswith(("sqlite_", "pragma_")) or tbl in TABLE_FUNCTIONS:
            return sqlite3.SQLITE_DENY
        if tbl in physical_tables and tbl not in KNOWN_TABLES:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    if action_code == sqlite3.SQLITE_FUNCTION:
        func = str(arg2).lower() if arg2 else ""
        if func in ALLOWED_FUNCTIONS:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    # Deny all other operations (ATTACH, DETACH, PRAGMA, writes, DDL, VACUUM, etc.)
    return sqlite3.SQLITE_DENY


def connect_ro(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """
    Opens an isolated, hardened read-only SQLite connection.
    Enforces mode=ro, query_only, authorizer, and resource limits.
    """
    resolved = Path(db_path).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Database file does not exist at {resolved}. Run init_db() first.")

    uri = f"{resolved.as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    try:
        # 1. Enforce query_only before locking down PRAGMAs
        conn.execute("PRAGMA query_only = ON;")

        # 2. Enforce resource limits
        conn.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_CELL_BYTES)
        conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, MAX_SQL_BYTES)

        # 3. Install authorizer (PRAGMAs cannot be changed after this). The table list is read
        # first, while nothing is restricted.
        physical = frozenset(
            str(name).lower()
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        )
        conn.set_authorizer(functools.partial(_security_authorizer, physical_tables=physical))
    except BaseException:
        conn.close()
        raise

    return conn


def execute_query(
    sql: str,
    db_path: str | Path = DEFAULT_DB_PATH,
    timeout_s: float = QUERY_TIMEOUT_S,
    max_rows: int = MAX_ROWS,
) -> tuple[list[str], list[tuple[Any, ...]], bool]:
    """
    Executes a read-only query under authorizer security and wall-clock timeout.
    Returns (columns, rows, is_truncated).
    """
    conn = connect_ro(db_path)
    try:
        deadline = time.monotonic() + timeout_s
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)

        cursor = conn.cursor()
        cursor.execute(sql)

        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        raw_rows = cursor.fetchmany(max_rows + 1)
        is_truncated = len(raw_rows) > max_rows
        rows = raw_rows[:max_rows]
        cursor.close()

        return columns, rows, is_truncated
    finally:
        conn.close()
