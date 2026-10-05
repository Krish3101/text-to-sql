"""Seed fingerprint, plus the join traps the README quotes, checked on the real data."""

import sqlite3

import pytest

from text_to_sql.config import SEED_VERSION
from text_to_sql.database import get_database_stats, init_db


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "seed.db"
    init_db(path, force=True)
    return path


@pytest.fixture
def conn(db):
    conn = sqlite3.connect(db)
    yield conn
    conn.close()


def one(conn, sql):
    return conn.execute(sql).fetchone()[0]


def test_row_counts(db):
    assert get_database_stats(db) == {
        "customers": 30,
        "products": 25,
        "orders": 75,
        "order_items": 180,
    }


def test_totals(conn):
    assert one(conn, "SELECT ROUND(SUM(total_amount), 2) FROM orders") == 50131.26
    assert one(conn, "SELECT SUM(quantity) FROM order_items") == 453


def test_database_checks_pass(conn):
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    assert one(conn, "PRAGMA user_version") == SEED_VERSION


def test_sqlite_sequence_has_one_row_per_table(conn):
    assert conn.execute("SELECT name, seq FROM sqlite_sequence ORDER BY name").fetchall() == [
        ("customers", 30),
        ("order_items", 180),
        ("orders", 75),
        ("products", 25),
    ]


def test_join_trap_fan_out(conn):
    # Each order repeats once per line item, so its total is counted several times.
    fanned_out = one(
        conn,
        "SELECT ROUND(SUM(o.total_amount), 2) FROM orders o "
        "JOIN order_items oi ON oi.order_id = o.order_id",
    )
    assert fanned_out == 130306.64
    assert one(conn, "SELECT ROUND(SUM(total_amount), 2) FROM orders") == 50131.26


def test_join_trap_inner_drops_customers_without_orders(conn):
    inner = one(
        conn,
        "SELECT COUNT(DISTINCT c.customer_id) FROM customers c "
        "JOIN orders o ON o.customer_id = c.customer_id",
    )
    left = one(
        conn,
        "SELECT COUNT(DISTINCT c.customer_id) FROM customers c "
        "LEFT JOIN orders o ON o.customer_id = c.customer_id",
    )
    no_orders = one(
        conn,
        "SELECT COUNT(*) FROM customers c "
        "LEFT JOIN orders o ON o.customer_id = c.customer_id WHERE o.order_id IS NULL",
    )
    assert (inner, left, no_orders) == (27, 30, 3)


def test_old_seed_version_is_rebuilt(tmp_path):
    path = tmp_path / "old.db"
    init_db(path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 0")
    conn.execute("DELETE FROM order_items")
    conn.commit()
    conn.close()

    init_db(path)

    conn = sqlite3.connect(path)
    assert one(conn, "PRAGMA user_version") == SEED_VERSION
    assert one(conn, "SELECT COUNT(*) FROM order_items") == 180
    conn.close()
    assert not path.with_suffix(".tmp").exists()
