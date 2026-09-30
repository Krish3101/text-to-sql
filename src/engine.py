"""Ties the pieces together: ask the model for SQL, check it, run it, return the rows."""

import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.database import get_readonly_connection, get_readwrite_connection
from src.guardrails import validate_sql_security
from src.providers import GenerationResult, OpenRouterProvider, SQLExtractor
from src.schema import get_schema_prompt_text

# SQLite calls the progress handler every 1,000 steps, so this stops a query after
# about a billion steps. That's far past anything the sample data needs, and it stops a
# runaway cross join instead of letting it hang the app.
MAX_PROGRESS_CALLS = 1_000_000


@dataclass
class QueryResult:
    natural_query: str
    generated_sql: str
    execution_time_ms: float
    is_safe: bool = True
    guardrail_error: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    error: str | None = None
    row_count: int = 0
    needs_approval: bool = False
    wrote: bool = False  # an approved write that ran

    @property
    def dataframe(self) -> pd.DataFrame | None:
        if not self.columns:
            return None
        return pd.DataFrame(self.rows, columns=self.columns)


def limit_query_steps(conn: sqlite3.Connection) -> None:
    calls = 0

    def handler() -> int:
        nonlocal calls
        calls += 1
        return 1 if calls > MAX_PROGRESS_CALLS else 0  # non-zero aborts the query

    conn.set_progress_handler(handler, 1000)


def validate_sqlite_syntax(sql: str, db_path: str) -> tuple[bool, str | None]:
    """Compile the query with EXPLAIN QUERY PLAN on a read-only connection. Nothing runs."""
    conn = None
    try:
        conn = get_readonly_connection(db_path)
        conn.execute(f"EXPLAIN QUERY PLAN {sql}")
        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        if conn:
            conn.close()


class TextToSQLEngine:
    """
    Generates SQL for a question, checks it, and runs it against the database.

    A read query that fails SQLite's syntax check is sent back to the model with the error
    attached, up to max_retries times, since a model given the actual error usually fixes
    a wrong column name on the next attempt.
    """

    def __init__(
        self, db_path: str = "ecommerce.db", api_key: str | None = None, max_retries: int = 2
    ):
        self.db_path = db_path
        self.max_retries = max_retries
        self.schema_info = get_schema_prompt_text()
        self.provider = OpenRouterProvider(api_key=api_key)

    @property
    def model(self) -> str:
        return self.provider.model

    def generate_sql(self, natural_query: str) -> GenerationResult:
        """Ask the model for SQL. If a read query doesn't compile, send it back with
        SQLite's error attached and ask again, up to max_retries times."""
        result = self.provider.generate_sql(natural_query, schema_info=self.schema_info)

        for _ in range(self.max_retries):
            sql = SQLExtractor.clean_sql(result.sql)
            if not result.success or not sql:
                break
            # Writes and rejected queries aren't retried: they go to approval or get
            # blocked, and either way the user sees them.
            is_safe, needs_approval, _ = validate_sql_security(sql)
            if not is_safe or needs_approval:
                break
            is_valid, err_msg = validate_sqlite_syntax(sql, self.db_path)
            if is_valid:
                break

            correction_prompt = (
                f"Your previous SQLite query:\n```sql\n{sql}\n```\n"
                f"failed with this SQLite error: {err_msg}\n"
                f"Original question: {natural_query}\n"
                "Correct the query using the exact schema columns provided. "
                "Return ONLY the corrected SQL in ```sql ... ```."
            )
            retry = self.provider.generate_sql(correction_prompt, schema_info=self.schema_info)
            if not retry.success or not retry.sql:
                break
            result = retry

        return result

    def execute_query(self, natural_query: str) -> QueryResult:
        """Generate the SQL, check it, and run it read-only."""
        start = time.perf_counter()

        def done(sql: str, **fields: Any) -> QueryResult:
            elapsed = (time.perf_counter() - start) * 1000.0
            return QueryResult(natural_query, sql, elapsed, **fields)

        gen_result = self.generate_sql(natural_query)
        sql = SQLExtractor.clean_sql(gen_result.sql)
        if not gen_result.success or not sql:
            return done(
                "",
                error=gen_result.error
                or "The model replied, but there was no SQL in its answer. Try asking again.",
            )

        is_safe, needs_approval, guardrail_err = validate_sql_security(sql)
        if not is_safe:
            return done(sql, is_safe=False, guardrail_error=guardrail_err, error=guardrail_err)
        if needs_approval:
            return done(sql, needs_approval=True)

        conn = None
        try:
            conn = get_readonly_connection(self.db_path)
            limit_query_steps(conn)
            cursor = conn.execute(sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
        except Exception as e:
            return done(sql, error=f"SQLite error: {e}")
        finally:
            if conn:
                conn.close()

        return done(sql, columns=columns, rows=rows, row_count=len(rows))

    def execute_approved_query(self, sql: str) -> QueryResult:
        """Run a write the user has approved."""
        start = time.perf_counter()
        cleaned_sql = SQLExtractor.clean_sql(sql)

        def done(**fields: Any) -> QueryResult:
            elapsed = (time.perf_counter() - start) * 1000.0
            return QueryResult("[Approved SQL]", cleaned_sql, elapsed, **fields)

        # Re-check before opening a read-write connection. The caller has normally
        # validated this SQL already, but this is the only path that can write, so it
        # doesn't take that on trust.
        is_safe, _, guardrail_err = validate_sql_security(cleaned_sql)
        if not is_safe:
            return done(is_safe=False, guardrail_error=guardrail_err, error=guardrail_err)

        conn = None
        try:
            conn = get_readwrite_connection(self.db_path)
            cursor = conn.execute(cleaned_sql)
            conn.commit()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall() if cursor.description else []
            return done(columns=columns, rows=rows, row_count=cursor.rowcount, wrote=True)
        except Exception as e:
            if conn:
                conn.rollback()
            return done(error=f"SQLite error: {e}")
        finally:
            if conn:
                conn.close()
