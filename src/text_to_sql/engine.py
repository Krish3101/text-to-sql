"""Text-to-SQL Engine: orchestrates generation, guardrails, and read-only execution."""

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from text_to_sql.config import DEFAULT_DB_PATH, MAX_RETRIES, MAX_ROWS, QUERY_TIMEOUT_S
from text_to_sql.executor import connect_ro, execute_query
from text_to_sql.guardrails import Verdict, validate_sql
from text_to_sql.llm import GenerationResult, OpenRouterProvider
from text_to_sql.schema import get_schema_prompt_text


@dataclass
class QueryResult:
    natural_query: str
    generated_sql: str
    execution_time_ms: float
    is_safe: bool = True
    verdict: Verdict | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    error: str | None = None
    row_count: int = 0
    truncated: bool = False
    refused: bool = False

    @property
    def dataframe(self) -> pd.DataFrame | None:
        if not self.columns:
            return None
        return pd.DataFrame(self.rows, columns=self.columns)


def validate_sqlite_syntax(sql: str, db_path: str | Path) -> tuple[bool, str | None]:
    """Compiles the query using EXPLAIN QUERY PLAN on an isolated read-only connection."""
    conn = None
    try:
        conn = connect_ro(db_path)
        conn.execute(f"EXPLAIN QUERY PLAN {sql}")
        return True, None
    except sqlite3.Error as e:
        return False, str(e)
    finally:
        if conn:
            conn.close()


class TextToSQLEngine:
    """Translates natural language questions to checked read-only SQLite queries."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
        api_key: str | None = None,
        max_retries: int = MAX_RETRIES,
        query_timeout_s: float = QUERY_TIMEOUT_S,
        max_rows: int = MAX_ROWS,
    ):
        self.db_path = Path(db_path).resolve()
        self.max_retries = max_retries
        self.query_timeout_s = query_timeout_s
        self.max_rows = max_rows
        self.schema_info = get_schema_prompt_text(self.db_path)
        self.provider = OpenRouterProvider(api_key=api_key)

    @property
    def model(self) -> str:
        return self.provider.model

    def generate_sql(self, natural_query: str) -> GenerationResult:
        """
        Asks the model for SQL.
        If a query produces a SQLite syntax error, retries with the error attached up to max_retries times.
        Refusals and destructive query rejections are never retried.
        """
        result = self.provider.generate_sql(natural_query, schema_info=self.schema_info)

        for _ in range(self.max_retries):
            # Nothing to fix, or the model refused: never retry
            if not result.success or not result.sql or result.refused:
                break

            sql = result.sql
            verdict = validate_sql(sql)

            # Do not retry on guardrail rejections of destructive/unauthorized commands
            if not verdict.allowed:
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
        """Generates SQL for a question, verifies it with guardrails, and executes read-only."""
        start = time.perf_counter()

        def done(sql: str, **fields: Any) -> QueryResult:
            elapsed = (time.perf_counter() - start) * 1000.0
            return QueryResult(natural_query, sql, elapsed, **fields)

        gen_result = self.generate_sql(natural_query)

        if gen_result.refused:
            return done(
                gen_result.sql,
                is_safe=False,
                refused=True,
                error="The request asks to modify data or schema, which is not permitted. Only read-only SELECT queries are supported.",
            )

        sql = gen_result.sql
        if not gen_result.success or not sql:
            return done(
                "",
                error=gen_result.error
                or "The model replied, but there was no SQL in its answer. Try asking again.",
            )

        # AST Guardrail check
        verdict = validate_sql(sql)
        if not verdict.allowed:
            return done(
                sql,
                is_safe=False,
                verdict=verdict,
                error=verdict.reason,
            )

        # Read-only execution under SQLite authorizer and timeout
        try:
            columns, rows, is_truncated = execute_query(
                sql,
                self.db_path,
                timeout_s=self.query_timeout_s,
                max_rows=self.max_rows,
            )
            return done(
                sql,
                verdict=verdict,
                columns=columns,
                rows=rows,
                row_count=len(rows),
                truncated=is_truncated,
            )
        except sqlite3.OperationalError as e:
            err_str = str(e)
            if "interrupted" in err_str.lower():
                return done(
                    sql,
                    verdict=verdict,
                    error=f"Query execution timed out (exceeded {self.query_timeout_s}s wall-clock limit).",
                )
            return done(sql, verdict=verdict, error=f"SQLite error: {e}")
        except sqlite3.Error as e:
            return done(sql, verdict=verdict, error=f"SQLite error: {e}")
