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


def test_approved_query_revalidates_before_writing(tmp_path):
    """The write path must not trust its caller: Layer 2 runs again before it opens
    a read-write connection."""
    from src.engine import TextToSQLEngine

    engine = TextToSQLEngine(db_path=str(tmp_path / "scratch.db"))
    result = engine.execute_approved_query("ATTACH DATABASE '/tmp/evil.db' AS evil")

    assert result.is_safe is False
    assert result.guardrail_error is not None
    assert "attach" in result.guardrail_error.lower()


class ScriptedProvider:
    """Stands in for OpenRouter and replies with the given SQL, in order."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def is_available(self):
        return True

    def generate_sql(self, prompt, schema_info=""):
        from src.providers import GenerationResult

        self.prompts.append(prompt)
        sql = self.replies.pop(0)
        return GenerationResult(
            sql=sql, raw_response=sql, provider="test", model="test", latency_ms=0.0, success=True
        )


def test_query_that_fails_to_compile_is_sent_back_with_the_error(tmp_path):
    db_file = str(tmp_path / "retry.db")
    init_db(db_file)
    engine = TextToSQLEngine(db_path=db_file)
    provider = ScriptedProvider(
        "SELECT nme FROM customers LIMIT 1",
        "SELECT first_name FROM customers LIMIT 1",
    )
    engine.primary_provider = provider

    result = engine.execute_query("What is the first customer's name?")

    assert result.error is None
    assert len(result.rows) == 1
    assert len(provider.prompts) == 2
    assert "no such column: nme" in provider.prompts[1]


def test_approved_write_is_marked_as_a_write(tmp_path):
    db_file = str(tmp_path / "write.db")
    init_db(db_file)
    engine = TextToSQLEngine(db_path=db_file)

    result = engine.execute_approved_query("UPDATE products SET price = price WHERE product_id = 1")

    assert result.error is None
    assert result.wrote is True
