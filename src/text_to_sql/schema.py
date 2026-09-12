"""Reads the schema for the prompt and the Schema tab. Nothing here is typed by hand."""

import sqlite3
from contextlib import closing
from pathlib import Path

import sqlglot
from sqlglot import exp

from text_to_sql.config import DEFAULT_DB_PATH, SCHEMA_PATH

DATE_TYPES = {"DATE", "DATETIME", "TIMESTAMP"}
MAX_LISTED_VALUES = 10


def _tables_in_schema_file() -> tuple[str, ...]:
    statements = sqlglot.parse(SCHEMA_PATH.read_text(encoding="utf-8"), read="sqlite")
    return tuple(
        s.find(exp.Table).name
        for s in statements
        if isinstance(s, exp.Create) and s.kind == "TABLE"
    )


# The four tables, in schema.sql order. The guardrail and the executor both use this set.
TABLES = _tables_in_schema_file()
KNOWN_TABLES = frozenset(TABLES)


def _connect(db_path: str | Path) -> sqlite3.Connection:
    # Our own fixed queries, so a plain read-only connection is enough here.
    return sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)


def table_ddl(db_path: str | Path = DEFAULT_DB_PATH) -> list[str]:
    """The CREATE TABLE text exactly as SQLite stores it, comments included."""
    placeholders = ", ".join("?" for _ in TABLES)
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            f"SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name IN ({placeholders})",
            TABLES,
        ).fetchall()
    ddl = dict(rows)
    return [ddl[table] for table in TABLES]


def data_notes(db_path: str | Path = DEFAULT_DB_PATH) -> list[str]:
    """Value lists for short TEXT columns and the range of each date column. Never rows."""
    notes = []
    with closing(_connect(db_path)) as conn:
        for table in TABLES:
            for _, column, col_type, *_ in conn.execute(f'PRAGMA table_info("{table}")'):
                col_type = col_type.upper()
                if col_type in DATE_TYPES:
                    low, high = conn.execute(
                        f'SELECT MIN("{column}"), MAX("{column}") FROM "{table}"'
                    ).fetchone()
                    notes.append(f"- {table}.{column} goes from '{low}' to '{high}'")
                elif col_type == "TEXT":
                    values = [
                        v
                        for (v,) in conn.execute(
                            f'SELECT DISTINCT "{column}" FROM "{table}" '
                            f'WHERE "{column}" IS NOT NULL ORDER BY 1 LIMIT {MAX_LISTED_VALUES + 1}'
                        )
                    ]
                    if len(values) <= MAX_LISTED_VALUES:
                        quoted = ", ".join(f"'{v}'" for v in values)
                        notes.append(f"- {table}.{column} values in the data: {quoted}")
    return notes


def schema_text(db_path: str | Path = DEFAULT_DB_PATH) -> str:
    """Schema block for the system prompt: the stored CREATE TABLE text plus the data notes."""
    return "\n\n".join(
        [
            *table_ddl(db_path),
            "DATA NOTES (generated from the current data):\n" + "\n".join(data_notes(db_path)),
        ]
    )


def describe_tables(db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, dict]:
    """Columns and foreign keys per table for the Schema tab, from PRAGMA table_info and foreign_key_list."""
    tables = {}
    with closing(_connect(db_path)) as conn:
        for table in TABLES:
            columns = [
                {
                    "Column": name,
                    "Type": col_type,
                    "Not null": bool(notnull),
                    "Primary key": bool(pk),
                }
                for _, name, col_type, notnull, _, pk in conn.execute(
                    f'PRAGMA table_info("{table}")'
                )
            ]
            foreign_keys = [
                {"column": row[3], "table": row[2], "references": row[4]}
                for row in conn.execute(f'PRAGMA foreign_key_list("{table}")')
            ]
            tables[table] = {"columns": columns, "foreign_keys": foreign_keys}
    return tables
