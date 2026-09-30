"""
Checks generated SQL before it is allowed to run.

Queries are parsed with sqlglot rather than scanned for banned keywords, so
multiple statements, ATTACH/DETACH and PRAGMA writable_schema are rejected by
what the statement actually is. Reads then run on a connection opened mode=ro;
writes are classified here and need approval before execution.
"""

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, SqlglotError


def _strip_markdown_and_formatting(sql: str) -> str:
    """Strips markdown code blocks, backticks, and extra whitespace."""
    cleaned = sql.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:sql|SQL)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def validate_sql_security(sql: str) -> tuple[bool, bool, str | None]:
    """
    Validates SQL query against AST security rules using sqlglot.

    Checks performed:
      1. Empty query rejection
      2. Multi-statement / stacked-query rejection
      3. AST expression classification (SELECT vs mutation/DDL operations)

    Returns:
        (is_safe, needs_approval, error_message)
    """
    cleaned_sql = _strip_markdown_and_formatting(sql)

    if not cleaned_sql:
        return False, False, "SQL query is empty or contains only whitespace."

    try:
        parsed_statements = sqlglot.parse(cleaned_sql, read="sqlite")
    except ParseError as e:
        return False, False, f"Failed to parse SQL AST: {e!s}"
    except SqlglotError as e:
        return False, False, f"Unexpected SQL parse error: {e!s}"

    # Filter out empty statements
    statements = [stmt for stmt in parsed_statements if stmt is not None]

    if not statements:
        return False, False, "SQL query does not contain any executable statements."

    if len(statements) > 1:
        return (
            False,
            False,
            f"Multiple SQL statements detected ({len(statements)}). Stacked queries are prohibited.",
        )

    statement = statements[0]
    stmt_key = getattr(statement, "key", "").lower()

    # Block administrative and dangerous commands
    if stmt_key in ("attach", "detach", "pragma") or isinstance(statement, (exp.Pragma,)):
        return (
            False,
            False,
            f"Disallowed SQL command '{stmt_key.upper()}'. Administrative operations are prohibited.",
        )

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
