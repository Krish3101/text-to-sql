"""Tests for executor.py: the read-only connection, the row cap and the deadline."""

import sqlite3

import pytest

from text_to_sql.database import init_db
from text_to_sql.executor import connect_ro, run_query


@pytest.fixture(scope="module")
def seeded_db(tmp_path_factory):
    db_file = tmp_path_factory.mktemp("db") / "test_ecommerce.db"
    init_db(db_file)
    return db_file


def test_readonly_connection_blocks_writes(seeded_db):
    conn = connect_ro(seeded_db)
    try:
        with pytest.raises((sqlite3.DatabaseError, sqlite3.OperationalError)):
            conn.execute(
                "INSERT INTO customers (first_name, last_name, email, city, state) "
                "VALUES ('Fail', 'User', 'fail@test.com', 'NYC', 'NY');"
            )
    finally:
        conn.close()


def test_executor_row_cap(seeded_db):
    """Verifies that large result sets are capped at 1,000 rows with is_truncated=True."""
    cross_join = "SELECT a.item_id, b.item_id FROM order_items a, order_items b LIMIT 2000"
    cols, rows, is_truncated = run_query(cross_join, seeded_db, max_rows=1000)
    assert len(rows) == 1000
    assert is_truncated is True


def test_executor_timeout(seeded_db):
    """Verifies that runaway queries are stopped by wall-clock timeout."""
    infinite_cte = (
        "WITH RECURSIVE inf(x) AS ("
        "  SELECT 1 UNION ALL SELECT x + 1 FROM inf"
        ") SELECT COUNT(*) FROM inf"
    )
    with pytest.raises(sqlite3.OperationalError) as exc_info:
        run_query(infinite_cte, seeded_db, timeout_s=0.5)

    assert "interrupted" in str(exc_info.value).lower()
