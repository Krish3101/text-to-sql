"""Asks the model 20 questions and prints how many it gets right.

Each question has a reference query written by hand. An answer counts as correct when it returns
the same rows as the reference, in any order. Column names don't matter, but extra or missing
columns do. Run from the project root with OPENROUTER_API_KEY in .env:

    uv run python -m scripts.eval

It uses up to 40 model calls, close to the free tier's 50 requests a day.
"""

import os
import sqlite3
import sys
import time
from contextlib import closing

from dotenv import load_dotenv

from text_to_sql.config import DEFAULT_DB_PATH, get_model
from text_to_sql.database import init_db
from text_to_sql.engine import answer

QUESTIONS = [
    ("How many customers are there?", "SELECT COUNT(*) FROM customers"),
    (
        "How many products are in the Electronics category?",
        "SELECT COUNT(*) FROM products WHERE category = 'Electronics'",
    ),
    (
        "What is the name of the most expensive product?",
        "SELECT product_name FROM products ORDER BY price DESC LIMIT 1",
    ),
    ("How many orders were cancelled?", "SELECT COUNT(*) FROM orders WHERE status = 'Cancelled'"),
    (
        "What is the combined total amount of all delivered orders?",
        "SELECT SUM(total_amount) FROM orders WHERE status = 'Delivered'",
    ),
    (
        "What is the average product price in each category? Return the category and the average.",
        "SELECT category, AVG(price) FROM products GROUP BY category",
    ),
    (
        "How many customers are in the VIP segment?",
        "SELECT COUNT(*) FROM customers WHERE customer_segment = 'VIP'",
    ),
    (
        "Which payment method is used on the most orders?",
        "SELECT payment_method FROM orders GROUP BY payment_method ORDER BY COUNT(*) DESC LIMIT 1",
    ),
    (
        "List the first and last names of customers who have never placed an order.",
        "SELECT first_name, last_name FROM customers"
        " WHERE customer_id NOT IN (SELECT customer_id FROM orders)",
    ),
    (
        "How many units have been sold in each product category? Return the category and the total.",
        "SELECT p.category, SUM(oi.quantity) FROM order_items oi"
        " JOIN products p ON p.product_id = oi.product_id GROUP BY p.category",
    ),
    (
        "How many orders were placed in 2025?",
        "SELECT COUNT(*) FROM orders WHERE strftime('%Y', order_date) = '2025'",
    ),
    (
        "What are the names of the three highest rated products?",
        "SELECT product_name FROM products ORDER BY rating DESC LIMIT 3",
    ),
    (
        "How much has Alice Johnson spent in total across her orders?",
        "SELECT SUM(o.total_amount) FROM orders o JOIN customers c ON c.customer_id = o.customer_id"
        " WHERE c.first_name = 'Alice' AND c.last_name = 'Johnson'",
    ),
    (
        "How many different customers have placed at least one order?",
        "SELECT COUNT(DISTINCT customer_id) FROM orders",
    ),
    (
        "Which products are out of stock? Return their names.",
        "SELECT product_name FROM products WHERE stock_quantity = 0",
    ),
    (
        "List the names of products that have never been ordered.",
        "SELECT product_name FROM products"
        " WHERE product_id NOT IN (SELECT product_id FROM order_items)",
    ),
    (
        "What is the average order total for each payment method? Return the method and the average.",
        "SELECT payment_method, AVG(total_amount) FROM orders GROUP BY payment_method",
    ),
    (
        "How many orders were shipped to the state CA?",
        "SELECT COUNT(*) FROM orders WHERE shipping_state = 'CA'",
    ),
    (
        "How many orders has Carol Williams placed?",
        "SELECT COUNT(*) FROM orders o JOIN customers c ON c.customer_id = o.customer_id"
        " WHERE c.first_name = 'Carol' AND c.last_name = 'Williams'",
    ),
    (
        "How many products are no longer active?",
        "SELECT COUNT(*) FROM products WHERE is_active = 0",
    ),
]


def normalise(rows):
    """Round floats so 1754.0 and 1754.00000001 compare equal, then sort."""
    out = [tuple(round(v, 2) if isinstance(v, float) else v for v in row) for row in rows]
    return sorted(out, key=repr)


def main():
    load_dotenv()
    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        sys.exit("Add OPENROUTER_API_KEY to .env first.")

    init_db(DEFAULT_DB_PATH)
    correct = 0
    with closing(sqlite3.connect(DEFAULT_DB_PATH)) as conn:
        for i, (question, reference) in enumerate(QUESTIONS, 1):
            expected = normalise(conn.execute(reference).fetchall())
            result = answer(question)
            ok = result.error is None and normalise(result.rows) == expected
            correct += ok
            print(f"{'PASS' if ok else 'FAIL'}  {i:2}. {question}")
            if result.error:
                print(f"        {result.error}")  # a rate-limit message means the score is low
            time.sleep(3)  # stay under the free tier's per-minute limit

    print(f"\n{correct}/{len(QUESTIONS)} correct with {get_model()}")


if __name__ == "__main__":
    main()
