"""Tests for executor.py: read-only defense-in-depth, authorizer, caps, and timeouts."""

import sqlite3
from pathlib import Path

import pytest

from text_to_sql.database import init_db
from text_to_sql.executor import connect_ro, execute_query
from text_to_sql.guardrails import validate_sql


@pytest.fixture(scope="module")
def seeded_db(tmp_path_factory):
    db_file = tmp_path_factory.mktemp("db") / "test_ecommerce.db"
    init_db(db_file, force=True)
    return db_file


def _get_fingerprint(db_path: Path) -> tuple[int, int, int, int, float]:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        c_count = cur.execute("SELECT COUNT(*) FROM customers;").fetchone()[0]
        p_count = cur.execute("SELECT COUNT(*) FROM products;").fetchone()[0]
        o_count = cur.execute("SELECT COUNT(*) FROM orders;").fetchone()[0]
        i_count = cur.execute("SELECT COUNT(*) FROM order_items;").fetchone()[0]
        total = cur.execute("SELECT ROUND(SUM(total_amount), 2) FROM orders;").fetchone()[0]
        return (c_count, p_count, o_count, i_count, total)
    finally:
        conn.close()


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


@pytest.mark.parametrize(
    "attack_sql,expected_file",
    [
        ("DROP TABLE customers", None),
        ("DELETE FROM orders", None),
        ("ATTACH DATABASE 'test_leak.db' AS leak", "test_leak.db"),
        ("ATTACH 'test_leak2.db' AS leak2", "test_leak2.db"),
        ("VACUUM INTO 'test_vacuum.db'", "test_vacuum.db"),
        ("PRAGMA query_only = OFF", None),
        ("SELECT randomblob(2000000)", None),
        ("CREATE TEMP TABLE evil AS SELECT 1", None),
        ("SELECT * FROM sqlite_master", None),
        ("SELECT COUNT(*) FROM sqlite_master", None),
        ("SELECT COUNT(*) FROM json_each('[1, 2]')", None),
    ],
)
def test_db_layer_blocks_without_guardrail(tmp_path, attack_sql, expected_file):
    """
    Runs the attack straight on the read-only connection, skipping the AST guardrail,
    to show the authorizer and setlimit hold on their own.
    """
    db_file = tmp_path / "defense_test.db"
    init_db(db_file)
    initial_fp = _get_fingerprint(db_file)

    if expected_file:
        target_path = tmp_path / expected_file
        attack_sql = attack_sql.replace(expected_file, str(target_path))

    conn = connect_ro(db_file)
    try:
        with pytest.raises((sqlite3.DatabaseError, sqlite3.OperationalError, sqlite3.DataError)):
            conn.execute(attack_sql)
    finally:
        conn.close()

    # Verify no file was created
    if expected_file:
        assert not target_path.exists(), (
            f"Vulnerability: file {target_path} was created by {attack_sql}!"
        )

    # Verify DB fingerprint remains completely unchanged
    assert _get_fingerprint(db_file) == initial_fp


def test_executor_row_cap(seeded_db):
    """Verifies that large result sets are capped at 1,000 rows with is_truncated=True."""
    cross_join = "SELECT a.item_id, b.item_id FROM order_items a, order_items b LIMIT 2000"
    cols, rows, is_truncated = execute_query(cross_join, seeded_db, max_rows=1000)
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
        execute_query(infinite_cte, seeded_db, timeout_s=0.5)

    assert "interrupted" in str(exc_info.value).lower()


def test_execute_query_normal(seeded_db):
    cols, rows, is_truncated = execute_query(
        "SELECT customer_id, first_name, email FROM customers LIMIT 5;", seeded_db
    )
    assert len(cols) == 3
    assert "customer_id" in cols
    assert len(rows) == 5
    assert is_truncated is False


def test_count_star_from_cte_still_runs(seeded_db):
    """The no-column read check must not block a plain COUNT(*) over a CTE."""
    sql = "WITH c AS (SELECT customer_id FROM orders) SELECT COUNT(*) FROM c"
    assert execute_query(sql, seeded_db)[1] == [(75,)]


@pytest.fixture
def db_with_hidden_table(tmp_path):
    db_file = tmp_path / "hidden.db"
    init_db(db_file)
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE hidden (secret TEXT)")
    conn.execute("INSERT INTO hidden VALUES ('x')")
    conn.commit()
    conn.close()
    return db_file


@pytest.mark.parametrize("sql", ["SELECT COUNT(*) FROM hidden", "SELECT 1 FROM hidden"])
def test_unlisted_table_denied_without_column_read(db_with_hidden_table, sql):
    """Layer 2 alone: no column is read, so only the table-level check can stop this."""
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        execute_query(sql, db_with_hidden_table)


def test_cte_and_known_tables_still_run_next_to_unlisted_table(db_with_hidden_table):
    recursive = "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 3) SELECT COUNT(*) FROM n"
    assert execute_query(recursive, db_with_hidden_table)[1] == [(3,)]
    cte = "WITH c AS (SELECT customer_id FROM orders) SELECT COUNT(*) FROM c"
    assert execute_query(cte, db_with_hidden_table)[1] == [(75,)]
    assert execute_query("SELECT COUNT(*) FROM orders", db_with_hidden_table)[1] == [(75,)]


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("SELECT '{\"a\": 5}' ->> '$.a'", 5),
        ("SELECT '{\"a\": 5}' -> '$.a'", "5"),
        ("SELECT json_extract('{\"a\": 5}', '$.a')", 5),
    ],
)
def test_json_operators_pass_both_layers(seeded_db, sql, expected):
    """Layer 1 allows the JSON operators, so Layer 2 must too."""
    assert validate_sql(sql).allowed
    assert execute_query(sql, seeded_db)[1] == [(expected,)]
