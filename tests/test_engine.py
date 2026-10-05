"""Tests for TextToSQLEngine: generation, checking, error retries, and refusals."""

import pytest

from text_to_sql.database import init_db
from text_to_sql.engine import TextToSQLEngine
from text_to_sql.extract import is_refusal
from text_to_sql.llm import GenerationResult


class ScriptedProvider:
    """Stands in for OpenRouter and returns scripted replies."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def is_available(self):
        return True

    def generate_sql(self, prompt, schema_info):
        self.prompts.append(prompt)
        sql = self.replies.pop(0)
        refused = is_refusal(sql)
        return GenerationResult(sql=sql, raw_response=sql, success=True, refused=refused)


@pytest.fixture
def engine(tmp_path):
    db_file = tmp_path / "engine_test.db"
    init_db(db_file)
    return TextToSQLEngine(db_path=db_file)


def ask(engine, *replies):
    engine.provider = ScriptedProvider(*replies)
    return engine.execute_query("a natural language question")


def test_read_query_runs(engine):
    res = ask(engine, "SELECT customer_id, first_name FROM customers LIMIT 3")
    assert res.is_safe is True
    assert res.error is None
    assert len(res.rows) == 3
    assert res.row_count == 3
    assert res.dataframe is not None


def test_write_query_is_rejected(engine):
    """Writing queries are rejected by guardrails without approval or execution."""
    res = ask(
        engine,
        "INSERT INTO customers (first_name, last_name, email, city, state) "
        "VALUES ('Alice', 'Test', 'alice.test@example.com', 'NYC', 'NY')",
    )
    assert res.is_safe is False
    assert res.error is not None
    assert res.rows == []


def test_refusal_handling(engine):
    """Explicit model refusal is mapped to refused outcome without retry."""
    provider = ScriptedProvider("-- REFUSE: read-only")
    engine.provider = provider
    res = engine.execute_query("Delete all cancelled orders")

    assert res.refused is True
    assert res.is_safe is False
    assert "not permitted" in res.error.lower()
    # Ensure no retry was attempted
    assert len(provider.prompts) == 1


def test_stacked_query_is_blocked(engine):
    res = ask(engine, "SELECT * FROM customers; DROP TABLE products;")
    assert res.is_safe is False
    assert "multiple" in res.error.lower() or "stacked" in res.error.lower()


def test_destructive_rejection_not_retried(engine):
    """Guardrail rejections on destructive queries should NOT be retried."""
    provider = ScriptedProvider("DROP TABLE customers")
    engine.provider = provider
    res = engine.execute_query("drop customers")

    assert res.is_safe is False
    assert len(provider.prompts) == 1


def test_query_that_fails_to_compile_is_sent_back_with_the_error(engine):
    """A syntax/column compilation error is retried with SQLite's error message."""
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


def test_timeout_reported_cleanly(engine):
    """Runaway queries report user-friendly timeout message."""
    infinite_sql = (
        "WITH RECURSIVE inf(x) AS ("
        "  SELECT 1 UNION ALL SELECT x + 1 FROM inf"
        ") SELECT COUNT(*) FROM inf"
    )
    engine.query_timeout_s = 0.5
    res = ask(engine, infinite_sql)
    assert res.error is not None
    assert "timed out" in res.error.lower()
