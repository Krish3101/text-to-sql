"""
Unit Tests for Security Guardrails (Layer 2 AST Validation & Rejection).
"""

import pytest

from src.guardrails import validate_sql_security


def test_valid_select_query():
    is_safe, needs_approval, err = validate_sql_security(
        "SELECT * FROM customers WHERE city = 'New York';"
    )
    assert is_safe is True
    assert needs_approval is False
    assert err is None


def test_valid_cte_query():
    sql = "WITH top_cust AS (SELECT customer_id FROM orders) SELECT * FROM top_cust;"
    is_safe, needs_approval, err = validate_sql_security(sql)
    assert is_safe is True
    assert needs_approval is False
    assert err is None


def test_write_query_classification():
    insert_sql = "INSERT INTO customers (first_name, last_name, email, city, state) VALUES ('John', 'Doe', 'john@test.com', 'Miami', 'FL');"
    is_safe, needs_approval, err = validate_sql_security(insert_sql)
    assert is_safe is True
    assert needs_approval is True
    assert err is None

    update_sql = "UPDATE products SET price = 99.99 WHERE product_id = 1;"
    is_safe, needs_approval, err = validate_sql_security(update_sql)
    assert is_safe is True
    assert needs_approval is True
    assert err is None

    delete_sql = "DELETE FROM customers WHERE customer_id = 100;"
    is_safe, needs_approval, err = validate_sql_security(delete_sql)
    assert is_safe is True
    assert needs_approval is True
    assert err is None


def test_multiple_statements_rejected():
    stacked_sql = "SELECT * FROM customers; DROP TABLE orders;"
    is_safe, needs_approval, err = validate_sql_security(stacked_sql)
    assert is_safe is False
    assert "multiple" in err.lower() or "stacked" in err.lower()


def test_empty_query_rejected():
    is_safe, needs_approval, err = validate_sql_security("   ")
    assert is_safe is False


def test_disallowed_attach_rejected():
    sql = 'ATTACH DATABASE "evil.db" AS evil;'
    is_safe, needs_approval, err = validate_sql_security(sql)
    assert is_safe is False
    assert "disallowed" in err.lower() or "attach" in err.lower()


def test_disallowed_pragma_rejected():
    sql = "PRAGMA writable_schema = 1;"
    is_safe, needs_approval, err = validate_sql_security(sql)
    assert is_safe is False
    assert "disallowed" in err.lower() or "pragma" in err.lower()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM products UNION SELECT id FROM orders",
        "SELECT id FROM products UNION ALL SELECT id FROM orders",
        "SELECT id FROM products EXCEPT SELECT id FROM orders",
        "SELECT id FROM products INTERSECT SELECT id FROM orders",
        "VALUES (1), (2)",
    ],
)
def test_set_operations_are_read_only(sql):
    """Set operations only read, so they must not be sent down the approval path."""
    is_safe, needs_approval, err = validate_sql_security(sql)
    assert is_safe is True
    assert needs_approval is False
    assert err is None
