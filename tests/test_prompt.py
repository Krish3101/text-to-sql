"""Tests for the generated prompt schema and the prompt rules."""

import re
import sqlite3

import pytest

from text_to_sql.database import init_db
from text_to_sql.prompt import build_system_prompt
from text_to_sql.schema import (
    KNOWN_TABLES,
    TABLES,
    data_notes,
    describe_tables,
    get_schema_prompt_text,
    table_ddl,
)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "prompt.db"
    init_db(path, force=True)
    return path


@pytest.fixture(scope="module")
def prompt(db):
    return build_system_prompt(get_schema_prompt_text(db))


def test_tables_come_from_schema_sql():
    assert TABLES == ("customers", "products", "orders", "order_items")
    assert KNOWN_TABLES == set(TABLES)


def test_prompt_schema_is_the_sqlite_master_text(db, prompt):
    conn = sqlite3.connect(db)
    stored = [
        conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (t,)).fetchone()[0]
        for t in TABLES
    ]
    conn.close()

    assert table_ddl(db) == stored
    assert get_schema_prompt_text(db).startswith("\n\n".join(stored))
    for ddl in stored:
        assert ddl in prompt


def test_column_comments_reach_the_prompt(prompt):
    assert "-- stored order total, rounded to cents" in prompt
    assert "-- price per unit when the order was placed" in prompt


def test_data_notes_list_real_categories_and_date_range(db, prompt):
    conn = sqlite3.connect(db)
    categories = [r[0] for r in conn.execute("SELECT DISTINCT category FROM products")]
    first, last = conn.execute("SELECT MIN(order_date), MAX(order_date) FROM orders").fetchone()
    conn.close()

    notes = "\n".join(data_notes(db))
    category_line = next(line for line in notes.splitlines() if "products.category" in line)
    assert len(categories) == 5
    for category in categories:
        assert f"'{category}'" in category_line
    assert f"orders.order_date goes from '{first}' to '{last}'" in notes
    assert notes in prompt


def test_data_notes_skip_columns_with_many_values(db):
    notes = "\n".join(data_notes(db))
    assert "customers.email" not in notes
    assert "customers.city" not in notes


def test_no_date_now_outside_the_prohibition(prompt):
    lines = [
        line
        for line in prompt.splitlines()
        if "date('now')" in line.lower() or "current_date" in line.lower()
    ]
    assert len(lines) == 1
    assert "never use" in lines[0]


@pytest.mark.parametrize("hint", [r"NOT\s+EXISTS", r"NOT\s+IN", r"LEFT\s+JOIN", r"IS\s+NULL"])
def test_no_anti_join_hints(prompt, hint):
    assert not re.search(rf"\b{hint}\b", prompt, re.IGNORECASE)


def test_refusal_rule_present(prompt):
    assert "Only SELECT queries are permitted" in prompt
    assert "\n-- REFUSE: read-only\n" in prompt


def test_describe_tables_reads_keys_from_the_database(db):
    tables = describe_tables(db)
    assert list(tables) == list(TABLES)
    assert tables["order_items"]["foreign_keys"] == [
        {"column": "product_id", "table": "products", "references": "product_id"},
        {"column": "order_id", "table": "orders", "references": "order_id"},
    ]
    pk = [c["Column"] for c in tables["customers"]["columns"] if c["Primary key"]]
    assert pk == ["customer_id"]
