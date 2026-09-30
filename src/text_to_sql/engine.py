"""Runs the steps for one question: prompt, model, parser check, compile retry, read-only run."""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from text_to_sql.config import DEFAULT_DB_PATH, MAX_RETRIES, QUERY_TIMEOUT_S
from text_to_sql.executor import connect_ro, run_query
from text_to_sql.guardrails import check_sql
from text_to_sql.llm import ask_model
from text_to_sql.prompt import build_system_prompt
from text_to_sql.schema import schema_text


@dataclass
class Answer:
    sql: str = ""
    allowed: bool | None = None  # None when there was no SQL to check
    reason: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    truncated: bool = False
    error: str | None = None


def compile_error(sql: str, db_path: str | Path) -> str | None:
    """SQLite's error if it cannot compile the query, else None. Nothing is run."""
    conn = connect_ro(db_path)
    try:
        conn.execute(f"EXPLAIN QUERY PLAN {sql}")
        return None
    except sqlite3.Error as e:
        return str(e)
    finally:
        conn.close()


def answer(
    question: str,
    ask: Callable[[str, str], str] = ask_model,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> Answer:
    """Turns a question into checked SQL and runs it. Tests pass a fake ask function."""
    system_prompt = build_system_prompt(schema_text(db_path))
    try:
        sql = ask(system_prompt, question)
        if not sql:
            return Answer(
                error="The model replied, but there was no SQL in its answer. Try asking again."
            )
        allowed, reason = check_sql(sql)

        # Only an allowed query that SQLite cannot compile goes back to the model.
        for _ in range(MAX_RETRIES):
            error = compile_error(sql, db_path) if allowed else None
            if error is None:
                break
            fixed = ask(
                system_prompt,
                f"Your previous SQLite query:\n```sql\n{sql}\n```\n"
                f"failed with this SQLite error: {error}\n"
                f"Original question: {question}\n"
                "Correct the query using the exact schema columns provided. "
                "Return ONLY the corrected SQL in ```sql ... ```.",
            )
            if not fixed:
                break
            sql = fixed
            allowed, reason = check_sql(sql)
    except RuntimeError as e:
        return Answer(error=str(e))

    if not allowed:
        return Answer(sql=sql, allowed=False, reason=reason)

    try:
        columns, rows, truncated = run_query(sql, db_path)
    except sqlite3.OperationalError as e:
        message = (
            f"Query execution timed out (exceeded {QUERY_TIMEOUT_S}s wall-clock limit)."
            if "interrupted" in str(e).lower()
            else f"SQLite error: {e}"
        )
        return Answer(sql=sql, allowed=True, reason=reason, error=message)
    except sqlite3.Error as e:
        return Answer(sql=sql, allowed=True, reason=reason, error=f"SQLite error: {e}")
    return Answer(sql, True, reason, columns, rows, truncated)
