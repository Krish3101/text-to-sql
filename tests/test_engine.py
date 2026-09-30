"""Tests for TextToSQLEngine: checking, running and approving queries."""

import pytest

from src.database import execute_readonly_query, init_db
from src.engine import TextToSQLEngine
from src.providers import GenerationResult


@pytest.fixture
def engine(tmp_path):
    db_file = str(tmp_path / "engine_test.db")
    init_db(db_file)
    return TextToSQLEngine(db_path=db_file)


def ask(engine, *replies):
    """Run a question through the engine with the model's replies scripted."""
    engine.provider = ScriptedProvider(*replies)
    return engine.execute_query("a question")


def test_read_query_runs(engine):
    res = ask(engine, "SELECT customer_id, first_name FROM customers LIMIT 3")
    assert res.is_safe is True
    assert res.needs_approval is False
    assert res.error is None
    assert len(res.rows) == 3
    assert res.dataframe is not None


def test_write_query_waits_for_approval(engine):
    res = ask(
        engine,
        "INSERT INTO customers (first_name, last_name, email, city, state) VALUES ('Alice', 'Test', 'alice.test@example.com', 'NYC', 'NY')",
    )
    assert res.is_safe is True
    assert res.needs_approval is True
    assert res.error is None
    assert res.rows == []


def test_approved_query_writes(engine):
    sql = "INSERT INTO products (product_name, category, price, cost, stock_quantity, rating, is_active) VALUES ('App Product', 'Electronics', 199.99, 100.0, 10, 4.9, 1);"
    res = engine.execute_approved_query(sql)
    assert res.error is None
    assert res.row_count == 1

    _, rows = execute_readonly_query(
        "SELECT * FROM products WHERE product_name = 'App Product'", engine.db_path
    )
    assert len(rows) == 1


def test_stacked_query_is_blocked(engine):
    res = ask(engine, "SELECT * FROM customers; DROP TABLE products;")
    assert res.is_safe is False
    assert "stacked" in res.guardrail_error.lower()


def test_approved_query_revalidates_before_writing(tmp_path):
    """The write path must not trust its caller: the guardrails run again before it
    opens a read-write connection."""
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
        self.prompts.append(prompt)
        sql = self.replies.pop(0)
        return GenerationResult(sql=sql, raw_response=sql, success=True)


def test_query_that_fails_to_compile_is_sent_back_with_the_error(engine):
    provider = ScriptedProvider(
        "SELECT nme FROM customers LIMIT 1",
        "SELECT first_name FROM customers LIMIT 1",
    )
    engine.provider = provider

    result = engine.execute_query("What is the first customer's name?")

    assert result.error is None
    assert len(result.rows) == 1
    assert len(provider.prompts) == 2
    assert "no such column: nme" in provider.prompts[1]


def test_approved_write_is_marked_as_a_write(engine):
    result = engine.execute_approved_query("UPDATE products SET price = price WHERE product_id = 1")

    assert result.error is None
    assert result.wrote is True
