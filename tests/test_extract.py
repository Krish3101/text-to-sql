"""Tests for extract.py: fence unwrapping, raw statement extraction, and refusal detection."""

from text_to_sql.extract import extract_sql, is_refusal


def test_sql_extractor_code_fences():
    raw = """Here is the query you requested:
```sql
SELECT customer_id, first_name FROM customers WHERE city = 'New York';
```
Hope that helps!"""
    sql = extract_sql(raw)
    assert sql == "SELECT customer_id, first_name FROM customers WHERE city = 'New York';"


def test_sql_extractor_sqlite_fence_tag():
    """Verify that ```sqlite is not mangled to ite\\nSELECT."""
    raw = """```sqlite
SELECT * FROM orders WHERE total_amount > 100;
```"""
    sql = extract_sql(raw)
    assert sql == "SELECT * FROM orders WHERE total_amount > 100;"


def test_sql_extractor_uppercase_sql_fence():
    raw = """```SQL
SELECT COUNT(*) FROM products;
```"""
    sql = extract_sql(raw)
    assert sql == "SELECT COUNT(*) FROM products;"


def test_sql_extractor_last_fence_wins():
    raw = """I considered this first query:
```sql
SELECT * FROM customers
```
But the correct query is:
```sql
SELECT customer_id, email FROM customers WHERE customer_segment = 'VIP'
```"""
    sql = extract_sql(raw)
    assert sql == "SELECT customer_id, email FROM customers WHERE customer_segment = 'VIP'"


def test_sql_extractor_raw_statement():
    raw = "Here is the query: SELECT product_name, price FROM products WHERE price > 50;"
    sql = extract_sql(raw)
    assert sql == "SELECT product_name, price FROM products WHERE price > 50;"


def test_sql_extractor_raw_with_statement():
    raw = "You can use this CTE: WITH ranked AS (SELECT * FROM orders) SELECT * FROM ranked;"
    sql = extract_sql(raw)
    assert sql == "WITH ranked AS (SELECT * FROM orders) SELECT * FROM ranked;"


def test_sql_extractor_no_sql_returns_empty():
    raw = "I am an AI assistant and I do not have sufficient information to answer."
    sql = extract_sql(raw)
    assert sql == ""


def test_sql_extractor_preserves_backticks_in_literals():
    """Verify that regex doesn't strip backticks from string literals."""
    raw = "SELECT * FROM customers WHERE email = 'user`test`@example.com';"
    sql = extract_sql(raw)
    assert "`test`" in sql


def test_sql_extractor_drops_prose_after_the_query():
    raw = "SELECT COUNT(*) FROM orders;\nThis counts every order."
    assert extract_sql(raw) == "SELECT COUNT(*) FROM orders;"


def test_sql_extractor_keeps_trailing_comment():
    raw = "```sql\nSELECT * FROM customers; -- note\n```"
    assert extract_sql(raw) == "SELECT * FROM customers; -- note"


def test_refusal_is_the_whole_reply():
    assert is_refusal("-- REFUSE: read-only")
    assert is_refusal("  -- refuse: read-only\n")
    assert is_refusal("```sql\n-- REFUSE: read-only\n```")
    assert is_refusal("`-- REFUSE: read-only`")


def test_refusal_text_inside_a_reply_is_not_a_refusal():
    assert not is_refusal("This request would modify data. -- REFUSE: read-only")
    assert not is_refusal("SELECT * FROM orders -- REFUSE: read-only")
    assert not is_refusal("")
