"""Tests for the AST guardrail: hand-written cases plus the attack corpus in attacks.yaml."""

from pathlib import Path

import pytest
import yaml

from text_to_sql.guardrails import Status, validate_sql

ATTACK_CASES = yaml.safe_load((Path(__file__).parent / "attacks.yaml").read_text(encoding="utf-8"))


def test_valid_select_query():
    verdict = validate_sql("SELECT * FROM customers WHERE city = 'New York';")
    assert verdict.status == Status.ALLOW
    assert verdict.allowed is True
    assert "allowed" in verdict.code.lower() or "read-only" in verdict.reason.lower()


def test_valid_cte_query():
    sql = "WITH top_cust AS (SELECT customer_id FROM orders) SELECT * FROM top_cust;"
    verdict = validate_sql(sql)
    assert verdict.status == Status.ALLOW
    assert verdict.allowed is True


def test_write_query_rejection():
    """Writes must be rejected immediately (write-approval flow is removed)."""
    insert_sql = "INSERT INTO customers (first_name, last_name, email, city, state) VALUES ('John', 'Doe', 'john@test.com', 'Miami', 'FL');"
    verdict = validate_sql(insert_sql)
    assert verdict.status == Status.REJECT
    assert verdict.allowed is False

    update_sql = "UPDATE products SET price = 99.99 WHERE product_id = 1;"
    verdict = validate_sql(update_sql)
    assert verdict.status == Status.REJECT
    assert verdict.allowed is False

    delete_sql = "DELETE FROM customers WHERE customer_id = 100;"
    verdict = validate_sql(delete_sql)
    assert verdict.status == Status.REJECT
    assert verdict.allowed is False


def test_multiple_statements_rejected():
    stacked_sql = "SELECT * FROM customers; DROP TABLE orders;"
    verdict = validate_sql(stacked_sql)
    assert verdict.status == Status.REJECT
    assert "multiple" in verdict.reason.lower() or "stacked" in verdict.reason.lower()


def test_empty_query_rejected():
    verdict = validate_sql("   ")
    assert verdict.status == Status.REJECT
    assert verdict.allowed is False


def test_disallowed_attach_rejected():
    sql = 'ATTACH DATABASE "evil.db" AS evil;'
    verdict = validate_sql(sql)
    assert verdict.status == Status.REJECT
    assert "disallowed" in verdict.reason.lower() or "attach" in verdict.reason.lower()


def test_disallowed_pragma_rejected():
    sql = "PRAGMA writable_schema = 1;"
    verdict = validate_sql(sql)
    assert verdict.status == Status.REJECT
    assert "disallowed" in verdict.reason.lower() or "pragma" in verdict.reason.lower()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM products UNION SELECT id FROM orders",
        "SELECT id FROM products UNION ALL SELECT id FROM orders",
        "SELECT id FROM products EXCEPT SELECT id FROM orders",
        "SELECT id FROM products INTERSECT SELECT id FROM orders",
    ],
)
def test_set_operations_are_allowed(sql):
    verdict = validate_sql(sql)
    assert verdict.status == Status.ALLOW
    assert verdict.allowed is True


def test_root_values_rejected():
    """Root VALUES row constructor without SELECT is rejected."""
    verdict = validate_sql("VALUES (1), (2)")
    assert verdict.status == Status.REJECT
    assert verdict.allowed is False


def test_values_subquery_allowed():
    """VALUES inside a FROM subquery is allowed."""
    verdict = validate_sql("SELECT * FROM (VALUES (1), (2))")
    assert verdict.status == Status.ALLOW
    assert verdict.allowed is True


def test_unknown_table_rejected():
    verdict = validate_sql("SELECT * FROM secret_passwords")
    assert verdict.status == Status.REJECT
    assert "not in the database schema" in verdict.reason.lower()


def test_sqlite_master_rejected():
    verdict = validate_sql("SELECT * FROM sqlite_master")
    assert verdict.status == Status.REJECT
    assert "not in the database schema" in verdict.reason.lower()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) FROM sqlite_master WHERE 0 IN (WITH sqlite_master AS (SELECT 1) SELECT 1)",
        "SELECT * FROM (WITH secret AS (SELECT 1) SELECT * FROM secret), secret",
    ],
)
def test_cte_name_only_counts_in_its_own_scope(sql):
    assert validate_sql(sql).code == "unknown_table"


def test_cte_visible_in_later_cte_and_subquery():
    sql = (
        "WITH a AS (SELECT customer_id FROM orders), b AS (SELECT * FROM a) "
        "SELECT * FROM b WHERE customer_id IN (SELECT customer_id FROM a)"
    )
    assert validate_sql(sql).allowed


def test_forbidden_functions_rejected():
    for func_sql in [
        "SELECT load_extension('x')",
        "SELECT writefile('a', 'b')",
        "SELECT readfile('/etc/passwd')",
        "SELECT fts3_tokenizer('x')",
    ]:
        verdict = validate_sql(func_sql)
        assert verdict.status == Status.REJECT
        assert "not permitted" in verdict.reason.lower() or "disallowed" in verdict.reason.lower()


def test_trailing_comment_tolerated():
    verdict = validate_sql("SELECT * FROM customers; -- note")
    assert verdict.status == Status.ALLOW
    assert verdict.allowed is True


@pytest.mark.parametrize(
    "case",
    ATTACK_CASES,
    ids=[f"{c['id']}-{c['expected']}" for c in ATTACK_CASES],
)
def test_attack_corpus(case):
    verdict = validate_sql(case["sql"])
    assert verdict.status.value == case["expected"], (
        f"{case['id']}: expected {case['expected']}, got {verdict.status.value} "
        f"({verdict.reason}) for SQL:\n{case['sql']}"
    )
