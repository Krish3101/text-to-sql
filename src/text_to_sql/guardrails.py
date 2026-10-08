"""The parser check: only a single read-only SELECT on known tables may reach SQLite.

- Exactly one statement; trailing semicolons and comments are fine.
- A SELECT, UNION, INTERSECT or EXCEPT at the root (a bare VALUES is rejected).
- No DML, DDL, PRAGMA, ATTACH, transaction or INTO anywhere in the tree.
- Every table is one of the four schema tables or a CTE name defined in the query.
"""

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from text_to_sql.schema import KNOWN_TABLES

FORBIDDEN_NODE_TYPES = (
    exp.DML,
    exp.DDL,
    exp.Command,
    exp.Pragma,
    exp.Attach,
    exp.Detach,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Analyze,
    exp.Into,
    exp.Set,
    exp.Use,
    exp.Copy,
    exp.Merge,
)

ALLOWED = (True, "Query allowed: read-only SELECT query.")


def check_sql(sql: str) -> tuple[bool, str]:
    """Returns (allowed, reason). Nothing is executed."""
    cleaned = (sql or "").strip()
    if not cleaned:
        return False, "SQL query is empty or contains only whitespace."

    try:
        parsed = sqlglot.parse(cleaned, read="sqlite")
    except SqlglotError as e:
        return False, f"Failed to parse SQL: {e!s}"
    except Exception as e:
        return False, f"SQL parse error: {e!s}"

    # Trailing semicolons and comments parse as None or Semicolon items.
    statements = [s for s in parsed if s is not None and not isinstance(s, exp.Semicolon)]
    if not statements:
        return False, "SQL query contains no executable statements."
    if len(statements) > 1:
        return (
            False,
            f"Multiple SQL statements detected ({len(statements)}). "
            "Stacked queries are prohibited.",
        )

    root = statements[0]
    first_keyword = cleaned.split()[0].upper()
    if not isinstance(root, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        return (
            False,
            f"Disallowed SQL statement '{first_keyword}'. Only SELECT queries are permitted; "
            "data modification and administrative operations are rejected.",
        )

    # A CTE name defined anywhere in the query may be read like a table.
    cte_names = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}

    for node in root.walk():
        if isinstance(node, FORBIDDEN_NODE_TYPES):
            return (
                False,
                f"Disallowed SQL operation '{first_keyword}' ({type(node).__name__}). "
                "Data modification, DDL, and administrative commands are prohibited.",
            )

        if isinstance(node, exp.Table):
            table = (node.name or "").lower()
            if not table:
                return False, "Table-valued functions are prohibited."

            qualifier = (node.db or node.catalog or "").lower()
            if qualifier and qualifier != "main":
                return (
                    False,
                    f"Database-qualified table reference '{qualifier}.{table}' is prohibited.",
                )

            if table not in KNOWN_TABLES and table not in cte_names:
                return False, f"Table '{table}' is not in the database schema."

    return ALLOWED
