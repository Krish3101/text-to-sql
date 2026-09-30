"""Ties the pieces together: ask the model for SQL, check it, run it, return the rows."""

import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any

try:
    import pandas as pd
except ImportError:
    pd = None

from src.database import (
    execute_readonly_query,
    get_readonly_connection,
    get_readwrite_connection,
    get_resolved_db_path,
)
from src.guardrails import (
    validate_sql_security,
)
from src.providers import (
    GenerationResult,
    OpenRouterProvider,
    SQLExtractor,
)
from src.schema import get_schema_prompt_text


@dataclass
class QueryResult:
    natural_query: str
    generated_sql: str
    is_safe: bool
    guardrail_error: str | None
    columns: list[str]
    rows: list[tuple[Any, ...]]
    dataframe: Any | None # pd.DataFrame if pandas is available
    execution_time_ms: float
    provider_used: str
    error: str | None = None
    row_count: int = 0
    needs_approval: bool = False
    wrote: bool = False  # an approved write that ran
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.row_count == 0 and self.rows:
            self.row_count = len(self.rows)
        if self.dataframe is None and pd is not None and self.columns is not None and self.rows is not None:
            try:
                self.dataframe = pd.DataFrame(self.rows, columns=self.columns)
            except Exception:
                self.dataframe = None


class SQLiteTimeoutGuard:
    """Limits maximum query execution steps / CPU cycles to prevent Cartesian stalls."""

    @staticmethod
    def attach_progress_limit(conn: sqlite3.Connection, max_steps: int = 1_000_000) -> None:
        step_counter = [0]

        def handler():
            step_counter[0] += 1
            if step_counter[0] > max_steps:
                return 1 # Non-zero return aborts query with sqlite3.OperationalError
            return 0

        conn.set_progress_handler(handler, 1000)


def validate_sqlite_syntax(sql: str, db_path: str = "ecommerce.db") -> tuple[bool, str | None]:
    """
    Validates SQL syntax against SQLite using EXPLAIN QUERY PLAN in read-only mode.
    Does not execute table scans or modify any data.
    """
    if not sql or not sql.strip():
        return False, "Empty SQL query."

    try:
        resolved = get_resolved_db_path(db_path)
        uri = f"{resolved.as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=3.0) as conn:
            cursor = conn.cursor()
            cursor.execute(f"EXPLAIN QUERY PLAN {sql}")
        return True, None
    except sqlite3.OperationalError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


class TextToSQLEngine:
    """
    Generates SQL for a question, checks it, and runs it against the database.

    A query that fails SQLite's syntax check is sent back to the model with the error
    attached, up to max_retries times, since a model given the actual error usually
    fixes a wrong column name on the next attempt.
    """

    def __init__(
        self,
        db_path: str = "ecommerce.db",
        provider: str = "openrouter",
        api_key: str | None = None,
        model: str | None = None,
        max_retries: int = 2
    ):
        self.db_path = db_path
        self.provider_type = provider.lower() if provider else "openrouter"
        self.api_key = api_key
        self.model = model or OpenRouterProvider.DEFAULT_MODEL
        self.max_retries = max_retries
        self.schema_info = get_schema_prompt_text()

        self.primary_provider = OpenRouterProvider(
            api_key=self.api_key,
            model=self.model
        )

    def set_provider(self, provider_type: str = "openrouter", api_key: str | None = None, model: str | None = None) -> None:
        """Dynamically reconfigures the active provider backend."""
        self.provider_type = provider_type.lower() if provider_type else "openrouter"
        if api_key is not None:
            self.api_key = api_key
        if model is not None:
            self.model = model

        self.primary_provider = OpenRouterProvider(
            api_key=self.api_key,
            model=self.model or OpenRouterProvider.DEFAULT_MODEL
        )

    def generate_sql(self, natural_query: str) -> GenerationResult:
        """Ask the model for SQL. If a read query doesn't compile, send it back with
        SQLite's error attached and ask again, up to max_retries times."""
        result = self.primary_provider.generate_sql(natural_query, schema_info=self.schema_info)

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
            retry = self.primary_provider.generate_sql(correction_prompt, schema_info=self.schema_info)
            if not retry.success or not retry.sql:
                break
            result = retry

        return result

    def execute_query(self, natural_query: str) -> QueryResult:
        """Generate the SQL, check it, and run it read-only."""
        start_time = time.perf_counter()

        gen_result = self.generate_sql(natural_query)
        sql = SQLExtractor.clean_sql(gen_result.sql)

        if not gen_result.success or not sql:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return QueryResult(
                natural_query=natural_query,
                generated_sql="",
                is_safe=True,
                guardrail_error=None,
                columns=[],
                rows=[],
                dataframe=None,
                execution_time_ms=elapsed,
                provider_used=gen_result.provider,
                error=gen_result.error or "The model replied, but there was no SQL in its answer. Try asking again."
            )

        is_safe, needs_approval, guardrail_err = validate_sql_security(sql)
        if not is_safe:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return QueryResult(
                natural_query=natural_query,
                generated_sql=sql,
                is_safe=False,
                guardrail_error=guardrail_err,
                columns=[],
                rows=[],
                dataframe=None,
                execution_time_ms=elapsed,
                provider_used=gen_result.provider,
                error=f"Guardrail Security Violation: {guardrail_err}"
            )

        if needs_approval:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return QueryResult(
                natural_query=natural_query,
                generated_sql=sql,
                is_safe=True,
                guardrail_error=None,
                columns=[],
                rows=[],
                dataframe=None,
                execution_time_ms=elapsed,
                provider_used=gen_result.provider,
                error=None,
                needs_approval=True
            )

        conn = None
        try:
            conn = get_readonly_connection(self.db_path)
            SQLiteTimeoutGuard.attach_progress_limit(conn, max_steps=1_000_000)
            cursor = conn.cursor()
            cursor.execute(sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()

            elapsed = (time.perf_counter() - start_time) * 1000.0
            df = pd.DataFrame(rows, columns=columns) if pd is not None and columns else None

            return QueryResult(
                natural_query=natural_query,
                generated_sql=sql,
                is_safe=True,
                guardrail_error=None,
                columns=columns,
                rows=rows,
                dataframe=df,
                execution_time_ms=elapsed,
                provider_used=gen_result.provider,
                error=None
            )
        except sqlite3.OperationalError as e:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return QueryResult(
                natural_query=natural_query,
                generated_sql=sql,
                is_safe=True,
                guardrail_error=None,
                columns=[],
                rows=[],
                dataframe=None,
                execution_time_ms=elapsed,
                provider_used=gen_result.provider,
                error=f"SQLite Execution Error: {e!s}"
            )
        except Exception as e:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return QueryResult(
                natural_query=natural_query,
                generated_sql=sql,
                is_safe=True,
                guardrail_error=None,
                columns=[],
                rows=[],
                dataframe=None,
                execution_time_ms=elapsed,
                provider_used=gen_result.provider,
                error=f"Unexpected Execution Error: {e!s}"
            )
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def execute_raw_sql(self, sql: str) -> QueryResult:
        """
        Executes a user-supplied raw SQL query with full guardrails and timing.
        """
        start_time = time.perf_counter()
        cleaned_sql = SQLExtractor.clean_sql(sql)

        is_safe, needs_approval, guardrail_err = validate_sql_security(cleaned_sql)
        if not is_safe:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return QueryResult(
                natural_query="[Raw SQL]",
                generated_sql=cleaned_sql,
                is_safe=False,
                guardrail_error=guardrail_err,
                columns=[],
                rows=[],
                dataframe=None,
                execution_time_ms=elapsed,
                provider_used="manual",
                error=f"Guardrail Security Violation: {guardrail_err}"
            )

        if needs_approval:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return QueryResult(
                natural_query="[Raw SQL]",
                generated_sql=cleaned_sql,
                is_safe=True,
                guardrail_error=None,
                columns=[],
                rows=[],
                dataframe=None,
                execution_time_ms=elapsed,
                provider_used="manual",
                error=None,
                needs_approval=True
            )

        try:
            columns, rows = execute_readonly_query(cleaned_sql, self.db_path)
            elapsed = (time.perf_counter() - start_time) * 1000.0
            df = pd.DataFrame(rows, columns=columns) if pd is not None and columns else None
            return QueryResult(
                natural_query="[Raw SQL]",
                generated_sql=cleaned_sql,
                is_safe=True,
                guardrail_error=None,
                columns=columns,
                rows=rows,
                dataframe=df,
                execution_time_ms=elapsed,
                provider_used="manual",
                error=None
            )
        except Exception as e:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return QueryResult(
                natural_query="[Raw SQL]",
                generated_sql=cleaned_sql,
                is_safe=True,
                guardrail_error=None,
                columns=[],
                rows=[],
                dataframe=None,
                execution_time_ms=elapsed,
                provider_used="manual",
                error=f"Execution Error: {e!s}"
            )

    def execute_approved_query(self, sql: str) -> QueryResult:
        """
        Executes a previously approved write query.
        """
        start_time = time.perf_counter()
        cleaned_sql = SQLExtractor.clean_sql(sql)

        # Re-check before opening a read-write connection. The caller has normally
        # validated this SQL already, but this is the only path that can write, so it
        # doesn't take that on trust.
        is_safe, _, guardrail_err = validate_sql_security(cleaned_sql)
        if not is_safe:
            return QueryResult(
                natural_query="[Approved SQL]",
                generated_sql=cleaned_sql,
                is_safe=False,
                guardrail_error=guardrail_err,
                columns=[],
                rows=[],
                dataframe=None,
                execution_time_ms=(time.perf_counter() - start_time) * 1000.0,
                provider_used="manual",
                error=guardrail_err,
            )

        conn = None
        try:
            conn = get_readwrite_connection(self.db_path)
            cursor = conn.cursor()
            cursor.execute(cleaned_sql)
            conn.commit()

            rowcount = cursor.rowcount
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall() if cursor.description else []

            elapsed = (time.perf_counter() - start_time) * 1000.0
            df = pd.DataFrame(rows, columns=columns) if pd is not None and columns else None

            return QueryResult(
                natural_query="[Approved SQL]",
                generated_sql=cleaned_sql,
                is_safe=True,
                guardrail_error=None,
                columns=columns,
                rows=rows,
                dataframe=df,
                execution_time_ms=elapsed,
                provider_used="manual",
                error=None,
                needs_approval=False,
                wrote=True,
                row_count=rowcount
            )
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return QueryResult(
                natural_query="[Approved SQL]",
                generated_sql=cleaned_sql,
                is_safe=True,
                guardrail_error=None,
                columns=[],
                rows=[],
                dataframe=None,
                execution_time_ms=elapsed,
                provider_used="manual",
                error=f"Execution Error: {e!s}"
            )
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
