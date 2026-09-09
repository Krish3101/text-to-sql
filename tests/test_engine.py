"""
Unit Tests for TextToSQLEngine and Raw SQL Execution.
"""

import pytest

from src.database import init_db
from src.engine import TextToSQLEngine


@pytest.fixture(scope="module")
def test_engine(tmp_path_factory):
    db_file = tmp_path_factory.mktemp("data") / "engine_test.db"
    init_db(str(db_file), force=True)
    return TextToSQLEngine(db_path=str(db_file), provider="openrouter", api_key="")


def test_execute_raw_sql_readonly(test_engine):
    res = test_engine.execute_raw_sql("SELECT customer_id, first_name FROM customers LIMIT 3;")
    assert res.is_safe is True
    assert res.needs_approval is False
    assert res.error is None
    assert len(res.rows) == 3
    assert res.dataframe is not None


def test_execute_raw_sql_write_requires_approval(test_engine):
    sql = "INSERT INTO customers (first_name, last_name, email, city, state) VALUES ('Alice', 'Test', 'alice.test@example.com', 'NYC', 'NY');"
    res = test_engine.execute_raw_sql(sql)
    assert res.is_safe is True
    assert res.needs_approval is True
    assert res.error is None


def test_execute_approved_query(test_engine):
    sql = "INSERT INTO products (product_name, category, price, cost, stock_quantity, rating, is_active) VALUES ('App Product', 'Electronics', 199.99, 100.0, 10, 4.9, 1);"
    res = test_engine.execute_approved_query(sql)
    assert res.error is None
    assert res.row_count == 1

    # Verify insertion
    read_res = test_engine.execute_raw_sql("SELECT * FROM products WHERE product_name = 'App Product';")
    assert len(read_res.rows) == 1


def test_execute_raw_sql_blocked_on_stacked(test_engine):
    stacked = "SELECT * FROM customers; DROP TABLE products;"
    res = test_engine.execute_raw_sql(stacked)
    assert res.is_safe is False
    assert "guardrail" in res.error.lower() or "stacked" in res.error.lower()
