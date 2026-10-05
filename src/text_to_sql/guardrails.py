"""AST Security Guardrails for Text-to-SQL.

Enforces a strict AST allowlist:
- Only SELECT/UNION/INTERSECT/EXCEPT statements are permitted at the root.
- Rejects root VALUES.
- Walks the AST to reject any DML, DDL, Command, Pragma, Attach, Detach, Transaction, Into, etc.
- Functions sqlglot doesn't know must be on ALLOWED_FUNCTIONS (so load_extension, readfile, etc. fail).
- Enforces table allowlist (known schema tables and CTE names in scope only; blocks sqlite_master).
- Tolerates trailing semicolons and comments.
- Returns Verdict(status=ALLOW|REJECT, reason=str).
"""

from dataclasses import dataclass
from enum import Enum

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from text_to_sql.schema import KNOWN_TABLES


class Status(str, Enum):
    ALLOW = "ALLOW"
    REJECT = "REJECT"


# The one function allowlist, by SQLite's own names. The AST check uses it for functions sqlglot
# doesn't know, and the executor's SQLite authorizer checks every function call against it.
ALLOWED_FUNCTIONS = frozenset(
    {
        # aggregates
        "count", "sum", "avg", "min", "max", "total", "group_concat", "string_agg",
        # numbers
        "round", "abs", "sign", "trunc", "floor", "ceil", "ceiling", "random",
        # null handling and conditionals
        "coalesce", "ifnull", "nullif", "iif", "likely", "unlikely",
        # text
        "lower", "upper", "length", "octet_length", "substr", "substring", "trim", "ltrim",
        "rtrim", "replace", "instr", "printf", "format", "concat", "concat_ws", "char",
        "unicode", "hex", "quote", "typeof", "like", "glob",
        # dates
        "date", "time", "datetime", "julianday", "strftime", "unixepoch", "timediff",
        # window functions
        "row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "ntile", "lag",
        "lead", "first_value", "last_value", "nth_value",
        "sqlite_version",
    }
)  # fmt: skip

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


@dataclass(frozen=True)
class Verdict:
    status: Status
    reason: str
    code: str = ""

    @property
    def allowed(self) -> bool:
        return self.status == Status.ALLOW


def _cte_in_scope(table: exp.Table, name: str) -> bool:
    # A CTE name only counts where SQLite can see it: in the query that owns the WITH and below.
    # A CTE in a subquery must not unlock the same name in the outer query.
    ancestor = table.parent
    while ancestor is not None:
        with_ = ancestor.args.get("with_") or ancestor.args.get("with")
        if isinstance(with_, exp.With) and any(
            cte.alias_or_name.lower() == name for cte in with_.expressions
        ):
            return True
        ancestor = ancestor.parent
    return False


def validate_sql(sql: str) -> Verdict:
    """
    Validates a SQL query using AST inspection.
    Returns Verdict(status=ALLOW|REJECT, reason=str, code=str).
    """
    cleaned = (sql or "").strip()
    if not cleaned:
        return Verdict(
            status=Status.REJECT,
            reason="SQL query is empty or contains only whitespace.",
            code="empty",
        )

    try:
        parsed_statements = sqlglot.parse(cleaned, read="sqlite")
    except SqlglotError as e:
        return Verdict(
            status=Status.REJECT, reason=f"Failed to parse SQL: {e!s}", code="parse_error"
        )
    except Exception as e:
        return Verdict(status=Status.REJECT, reason=f"SQL parse error: {e!s}", code="parse_error")

    # Drop None and exp.Semicolon items (allows trailing semicolons, comments, and multiple semicolons)
    statements = [
        s for s in parsed_statements if s is not None and not isinstance(s, exp.Semicolon)
    ]

    if not statements:
        return Verdict(
            status=Status.REJECT,
            reason="SQL query contains no executable statements.",
            code="empty",
        )

    if len(statements) > 1:
        return Verdict(
            status=Status.REJECT,
            reason=f"Multiple SQL statements detected ({len(statements)}). Stacked queries are prohibited.",
            code="multiple_statements",
        )

    root = statements[0]

    # Root allowlist: Select, Union, Intersect, Except only. Reject root Values.
    if not isinstance(root, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        first_kw = cleaned.split()[0].upper() if cleaned.split() else "STATEMENT"
        return Verdict(
            status=Status.REJECT,
            reason=f"Disallowed SQL statement '{first_kw}'. Only SELECT queries are permitted; data modification and administrative operations are rejected.",
            code="disallowed_root",
        )

    # Walk entire AST for forbidden operations, functions, and table references
    for node in root.walk():
        # 1. Reject forbidden operations (DML, DDL, PRAGMA, ATTACH, VACUUM, INTO, etc.)
        if isinstance(node, FORBIDDEN_NODE_TYPES):
            node_name = type(node).__name__
            first_kw = cleaned.split()[0].upper() if cleaned.split() else node_name
            return Verdict(
                status=Status.REJECT,
                reason=f"Disallowed SQL operation '{first_kw}' ({node_name}). Data modification, DDL, and administrative commands are prohibited.",
                code="disallowed_node",
            )

        # 2. Functions sqlglot doesn't recognise must be on the allowlist
        # (load_extension, readfile, randomblob, ... all land here)
        if isinstance(node, exp.Anonymous):
            anon_name = node.name.lower()
            if anon_name not in ALLOWED_FUNCTIONS:
                return Verdict(
                    status=Status.REJECT,
                    reason=f"Disallowed function call '{anon_name}'. Only safe scalar functions are permitted.",
                    code="disallowed_function",
                )

        # 3. Check tables
        if isinstance(node, exp.Table):
            tbl_name = (getattr(node, "name", "") or "").lower()
            if not tbl_name:
                return Verdict(
                    status=Status.REJECT,
                    reason="Table-valued functions are prohibited.",
                    code="table_function",
                )

            # Check database/catalog qualification (e.g. y.customers, temp.orders)
            db_qualifier = (getattr(node, "db", "") or getattr(node, "catalog", "") or "").lower()
            if db_qualifier and db_qualifier != "main":
                return Verdict(
                    status=Status.REJECT,
                    reason=f"Database-qualified table reference '{db_qualifier}.{tbl_name}' is prohibited.",
                    code="qualified_table",
                )

            if tbl_name not in KNOWN_TABLES and not _cte_in_scope(node, tbl_name):
                return Verdict(
                    status=Status.REJECT,
                    reason=f"Table '{tbl_name}' is not in the database schema.",
                    code="unknown_table",
                )

    return Verdict(
        status=Status.ALLOW, reason="Query allowed: read-only SELECT query.", code="allowed"
    )
