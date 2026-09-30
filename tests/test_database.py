"""
Unit Tests for Database Layer & Seeding.
"""

import sqlite3

import pytest

from src.database import (
    execute_readonly_query,
    get_database_stats,
    get_readonly_connection,
    get_readwrite_connection,
    init_db,
    reset_database,
)


@pytest.fixture(scope="module")
def test_db(tmp_path_factory):
    db_file = tmp_path_factory.mktemp("data") / "test_ecommerce.db"
    init_db(str(db_file), force=True)
    return str(db_file)


def test_database_seeding_counts(test_db):
    stats = get_database_stats(test_db)
    assert stats["customers"] == 30
    assert stats["products"] == 25
    assert stats["orders"] == 75
    assert stats["order_items"] == 180


def test_readonly_connection_blocks_writes(test_db):
    conn = get_readonly_connection(test_db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO customers (first_name, last_name, email, city, state) VALUES ('Fail', 'User', 'fail@test.com', 'NYC', 'NY');"
            )
    finally:
        conn.close()


def test_execute_readonly_query(test_db):
    cols, rows = execute_readonly_query(
        "SELECT customer_id, first_name, email FROM customers LIMIT 5;", test_db
    )
    assert len(cols) == 3
    assert "customer_id" in cols
    assert len(rows) == 5


def test_foreign_key_enforcement(test_db):
    conn = get_readwrite_connection(test_db)
    try:
        # Inserting order with non-existent customer_id 9999 should violate foreign key constraint
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO orders (customer_id, status, total_amount) VALUES (9999, 'Pending', 50.0);"
            )
    finally:
        conn.close()


def test_reset_database(test_db):
    # Mutate DB
    conn = get_readwrite_connection(test_db)
    conn.execute(
        "INSERT INTO products (product_name, category, price, cost, stock_quantity, rating, is_active) VALUES ('Extra Product', 'Apparel', 19.99, 5.0, 10, 4.0, 1);"
    )
    conn.commit()
    conn.close()

    stats_before = get_database_stats(test_db)
    assert stats_before["products"] == 26

    # Reset
    reset_database(test_db)
    stats_after = get_database_stats(test_db)
    assert stats_after["products"] == 25
    assert stats_after["customers"] == 30
    assert stats_after["orders"] == 75
    assert stats_after["order_items"] == 180
