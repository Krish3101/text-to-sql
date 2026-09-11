"""
Checks generated SQL before it is allowed to run.

Queries are parsed with sqlglot rather than scanned for banned keywords, so
multiple statements, ATTACH/DETACH and PRAGMA writable_schema are rejected by
what the statement actually is. Reads then run on a connection opened mode=ro;
writes are classified here and need approval before execution.
"""

import re
import sqlite3
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from src.database import get_readonly_connection

class SecurityViolationError(Exception):
    """Base exception for all Text-to-SQL security guardrail violations."""
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class MultipleStatementsError(SecurityViolationError):
    """Raised when query chaining or stacked SQL statements are detected."""


class InvalidSQLError(SecurityViolationError):
    """Raised when input SQL is empty or syntactically invalid."""


class DatabaseReadOnlyError(SecurityViolationError):
    """Raised when the SQLite engine blocks a write or unauthorized command in read-only mode."""


def _strip_markdown_and_formatting(sql: str) -> str:
    """Strips markdown code blocks, backticks, and extra whitespace."""
    cleaned = sql.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:sql|SQL)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def validate_sql_security(
    sql: str,
    raise_on_error: bool = False
) -> tuple[bool, bool, str | None]:
    """
    Validates SQL query against AST security rules using sqlglot.

    Checks performed:
      1. Empty query rejection
      2. Multi-statement / stacked-query rejection
      3. AST expression classification (SELECT vs mutation/DDL operations)

    Args:
        sql: Raw SQL query string.
        raise_on_error: If True, raises a SecurityViolationError;
                        if False, returns (False, False, error_message).

    Returns:
        (is_safe, needs_approval, error_message)
    """
    cleaned_sql = _strip_markdown_and_formatting(sql)

    if not cleaned_sql:
        msg = "SQL query is empty or contains only whitespace."
        if raise_on_error:
            raise InvalidSQLError(msg)
        return False, False, msg

    try:
        parsed_statements = sqlglot.parse(cleaned_sql, read="sqlite")
    except ParseError as e:
        # Fallback error reporting
        msg = f"Failed to parse SQL AST: {e!s}"
        if raise_on_error:
            raise InvalidSQLError(msg)
        return False, False, msg
    except Exception as e:
        msg = f"Unexpected SQL parse error: {e!s}"
        if raise_on_error:
            raise InvalidSQLError(msg)
        return False, False, msg

    # Filter out empty statements
    statements = [stmt for stmt in parsed_statements if stmt is not None]

    if not statements:
        msg = "SQL query does not contain any executable statements."
        if raise_on_error:
            raise InvalidSQLError(msg)
        return False, False, msg

    if len(statements) > 1:
        msg = f"Multiple SQL statements detected ({len(statements)}). Stacked queries are prohibited."
        if raise_on_error:
            raise MultipleStatementsError(msg, {"statement_count": len(statements)})
        return False, False, msg

    statement = statements[0]
    stmt_key = getattr(statement, "key", "").lower()

    # Block administrative and dangerous commands
    if stmt_key in ("attach", "detach", "pragma") or isinstance(statement, (exp.Pragma,)):
        msg = f"Disallowed SQL command '{stmt_key.upper()}'. Administrative operations are prohibited."
        if raise_on_error:
            raise SecurityViolationError(msg)
        return False, False, msg

    # Deterministic AST classification using SQLGlot Expression types.
    # exp.Query covers SELECT, WITH-CTE selects and the set operations
    # (UNION / UNION ALL / EXCEPT / INTERSECT); exp.Values covers a bare
    # VALUES row constructor. All of these only read. Writes and DDL
    # (Insert, Update, Delete, Drop, Create, Alter) fall outside both.
    if isinstance(statement, (exp.Query, exp.Values)):
        needs_approval = False
    else:
        # INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, etc.
        needs_approval = True

    return True, needs_approval, None


def execute_safe_query(
    sql: str,
    db_path: str = "ecommerce.db",
    params: tuple[Any, ...] | None = None,
) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Validate the SQL, then run it on a connection opened read-only.

    Raises SecurityViolationError if the query is rejected, DatabaseReadOnlyError if
    it gets past validation and SQLite still refuses it as a write.
    """
    validate_sql_security(sql, raise_on_error=True)
    cleaned_sql = _strip_markdown_and_formatting(sql)

    try:
        conn = get_readonly_connection(db_path)
    except Exception as e:
        raise DatabaseReadOnlyError(f"Failed to open read-only database connection: {e!s}") from e

    try:
        cursor = conn.cursor()
        cursor.execute(cleaned_sql, params or ())
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return columns, rows
    except sqlite3.OperationalError as e:
        err_msg = str(e).lower()
        if "readonly" in err_msg or "attempt to write" in err_msg or "not authorized" in err_msg:
            raise DatabaseReadOnlyError(
                f"SQLite refused a write on the read-only connection: {e!s}",
                {"original_error": str(e)}
            ) from e
        raise
    finally:
        conn.close()
