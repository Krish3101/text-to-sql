"""Layer 1 AST Guardrail: verifies query structure before any database access.

- Exactly one statement; trailing semicolons and comments are fine.
- A SELECT, UNION, INTERSECT or EXCEPT at the root (bare VALUES or DML/DDL rejected).
- No DML, DDL, PRAGMA, ATTACH, transaction or INTO anywhere in the tree.
- Every function call is verified against ALLOWED_FUNCTIONS.
- Every table is one of the schema tables or an in-scope CTE name.
"""

import re
from dataclasses import dataclass
from enum import Enum

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from text_to_sql.schema import KNOWN_TABLES


class Status(str, Enum):
    ALLOW = "ALLOW"
    REJECT = "REJECT"


@dataclass(frozen=True)
class Verdict:
    status: Status
    reason: str
    code: str = ""

    @property
    def allowed(self) -> bool:
        return self.status == Status.ALLOW


ALLOWED_FUNCTIONS = frozenset(
    {
        # aggregates
        "count", "sum", "avg", "min", "max", "group_concat", "total",
        # numbers & math
        "round", "abs", "sign", "trunc", "floor", "ceil", "ceiling", "random", "sqrt",
        "pow", "power", "mod",
        # null handling and conditionals
        "coalesce", "ifnull", "nullif", "iif", "likely", "unlikely",
        # text
        "lower", "upper", "length", "octet_length", "substr", "substring", "trim",
        "ltrim", "rtrim", "replace", "instr", "printf", "format", "concat", "concat_ws",
        "char", "unicode", "hex", "quote", "typeof", "like", "glob",
        # dates
        "date", "time", "datetime", "julianday", "strftime", "unixepoch", "timediff",
        # window functions
        "row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "ntile",
        "lag", "lead", "first_value", "last_value", "nth_value",
        # system & JSON
        "sqlite_version", "json_extract", "->", "->>",
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

_NON_FUNCTION_NODES = (
    exp.Cast,
    exp.TryCast,
    exp.Case,
    exp.Exists,
    exp.Connector,
    exp.Collate,
    exp.TsOrDsToTimestamp,
    exp.TsOrDsToDate,
    exp.TsOrDsToDatetime,
    exp.TsOrDsToTime,
)
_FUNCTION_NAME = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\(")


def _function_name(node: exp.Func) -> str:
    """The name SQLite sees for a sqlglot function node (strftime is TimeToStr, char is Chr, etc.)."""
    if isinstance(node, exp.JSONExtractScalar):
        rendered = node.sql(dialect="sqlite")
        return "->>" if " ->> " in rendered else "json_extract"
    if isinstance(node, exp.JSONExtract):
        rendered = node.sql(dialect="sqlite")
        return "->" if " -> " in rendered else "json_extract"
    match = _FUNCTION_NAME.match(node.sql(dialect="sqlite"))
    if match:
        return match.group(1).lower()
    return type(node).sql_names()[0].lower()


def _cte_in_scope(table: exp.Table, name: str) -> bool:
    """A CTE name only counts where SQLite can see it: in the query that owns the WITH and below."""
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
    """Validates a SQL query using AST inspection. Returns Verdict(status, reason, code)."""
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
    first_keyword = cleaned.split()[0].upper() if cleaned.split() else "STATEMENT"
    if not isinstance(root, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        return Verdict(
            status=Status.REJECT,
            reason=f"Disallowed SQL statement '{first_keyword}'. Only SELECT queries are permitted; "
            "data modification and administrative operations are rejected.",
            code="disallowed_root",
        )

    for node in root.walk():
        if isinstance(node, FORBIDDEN_NODE_TYPES):
            node_name = type(node).__name__
            return Verdict(
                status=Status.REJECT,
                reason=f"Disallowed SQL operation '{first_keyword}' ({node_name}). "
                "Data modification, DDL, and administrative commands are prohibited.",
                code="disallowed_node",
            )

        # Function check
        func_name = None
        if isinstance(node, exp.Anonymous):
            func_name = node.name.lower()
        elif isinstance(node, exp.Match):
            func_name = "match"
        elif isinstance(node, exp.Func) and not isinstance(node, _NON_FUNCTION_NODES):
            func_name = _function_name(node)

        if func_name is not None and func_name not in ALLOWED_FUNCTIONS:
            return Verdict(
                status=Status.REJECT,
                reason=f"Disallowed function call '{func_name}'. Only safe scalar functions are permitted.",
                code="disallowed_function",
            )

        # Table checks
        if isinstance(node, exp.Table):
            table = (node.name or "").lower()
            if not table:
                return Verdict(
                    status=Status.REJECT,
                    reason="Table-valued functions are prohibited.",
                    code="table_function",
                )

            qualifier = (node.db or node.catalog or "").lower()
            if qualifier and qualifier != "main":
                return Verdict(
                    status=Status.REJECT,
                    reason=f"Database-qualified table reference '{qualifier}.{table}' is prohibited.",
                    code="qualified_table",
                )

            if table not in KNOWN_TABLES and not _cte_in_scope(node, table):
                return Verdict(
                    status=Status.REJECT,
                    reason=f"Table '{table}' is not in the database schema.",
                    code="unknown_table",
                )

    return Verdict(
        status=Status.ALLOW, reason="Query allowed: read-only SELECT query.", code="allowed"
    )


def check_sql(sql: str) -> tuple[bool, str]:
    """Compatibility wrapper returning (allowed, reason). Nothing is executed."""
    verdict = validate_sql(sql)
    return verdict.allowed, verdict.reason
