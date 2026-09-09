"""
SQLite Database Management Module for Text-to-SQL Generator.

Provides connection handling, read-only isolation (URI mode=ro), schema creation,
and deterministic realistic mock data population for the E-Commerce database.
"""

import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text

from src.schema import SCHEMA_DDL


def get_resolved_db_path(db_path: str = "ecommerce.db") -> Path:
    """Returns absolute resolved Path object for database file."""
    return Path(db_path).resolve()


def get_readwrite_connection(db_path: str = "ecommerce.db") -> sqlite3.Connection:
    """
    Returns a read-write SQLite connection.
    Enforces foreign key constraint checking.
    """
    resolved = get_resolved_db_path(db_path)
    conn = sqlite3.connect(str(resolved), timeout=10.0, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def get_readonly_connection(db_path: str = "ecommerce.db") -> sqlite3.Connection:
    """
    Returns a read-only SQLite connection using URI mode=ro.
    This provides Layer 3 C-level engine write isolation.
    Handles spaces and special characters cleanly via percent-encoded URI.
    """
    resolved = get_resolved_db_path(db_path)
    if not resolved.exists():
        raise FileNotFoundError(f"Database file does not exist at {resolved}. Run init_db() first.")

    uri_path = f"{resolved.as_uri()}?mode=ro"
    conn = sqlite3.connect(uri_path, uri=True, timeout=5.0, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA query_only = ON;")
    return conn


def execute_readonly_query(
    sql: str,
    db_path: str = "ecommerce.db"
) -> tuple[list[str], list[tuple[Any, ...]]]:
    """
    Executes a read-only query using the isolated read-only connection.
    Returns (columns, rows).
    """
    conn = get_readonly_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return columns, rows
    finally:
        conn.close()


_SQLA_ENGINES: dict[str, Any] = {}

def get_sqla_engine(db_path: str = "ecommerce.db"):
    """Returns a cached SQLAlchemy engine for the database."""
    resolved = get_resolved_db_path(db_path)
    if str(resolved) not in _SQLA_ENGINES:
        _SQLA_ENGINES[str(resolved)] = create_engine(f"sqlite:///{resolved}", echo=False)
    return _SQLA_ENGINES[str(resolved)]


def get_table_names(db_path: str = "ecommerce.db") -> list[str]:
    """Returns list of user tables in the database using SQLAlchemy inspector."""
    engine = get_sqla_engine(db_path)
    inspector = inspect(engine)
    return inspector.get_table_names()


def get_table_columns_metadata(table_name: str, db_path: str = "ecommerce.db") -> list[dict[str, Any]]:
    """Returns structured column metadata for a given table using SQLAlchemy inspector."""
    engine = get_sqla_engine(db_path)
    inspector = inspect(engine)
    return inspector.get_columns(table_name)


def get_table_schema(table_name: str, db_path: str = "ecommerce.db") -> str:
    """Returns the CREATE TABLE DDL for a given table."""
    conn = get_readonly_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?;",
            (table_name,)
        )
        row = cursor.fetchone()
        return row[0] if row else ""
    finally:
        conn.close()


def get_database_stats(db_path: str = "ecommerce.db") -> dict[str, int]:
    """Returns record count for all user tables in the database dynamically using SQLAlchemy."""
    engine = get_sqla_engine(db_path)
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    stats: dict[str, int] = {}
    with engine.connect() as conn:
        for table in tables:
            try:
                result = conn.execute(text(f"SELECT COUNT(*) FROM `{table}`;"))
                stats[table] = result.scalar() or 0
            except Exception:
                stats[table] = 0
    return stats


def seed_database(conn: sqlite3.Connection) -> None:
    """
    Populates the database with realistic, deterministic mock records:
      - 30 customers (6 VIP, 16 Regular, 5 New, 3 Inactive; 3 customers with 0 orders)
      - 25 products (5 categories; 2 unsold products; 2 out-of-stock products)
      - 75 orders (Delivered, Shipped, Processing, Pending, Cancelled)
      - 180 order_items (1-4 items per order, precise discounts, matching order totals)
    """
    cursor = conn.cursor()

    # Disable foreign keys temporarily during truncate/wipe
    cursor.execute("PRAGMA foreign_keys = OFF;")
    cursor.execute("DELETE FROM order_items;")
    cursor.execute("DELETE FROM orders;")
    cursor.execute("DELETE FROM products;")
    cursor.execute("DELETE FROM customers;")
    cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('customers', 'products', 'orders', 'order_items');")
    cursor.execute("PRAGMA foreign_keys = ON;")

    # 1. Seed Customers (30 records)
    # Segments: 6 VIP, 16 Regular, 5 New, 3 Inactive
    customers_data = [
        # VIP Customers (1 - 6)
        ("Alice", "Johnson", "alice.johnson@example.com", "555-0101", "New York", "NY", "USA", "10001", "2025-01-10 09:15:00", "VIP"),
        ("Bob", "Smith", "bob.smith@example.com", "555-0102", "Los Angeles", "CA", "USA", "90001", "2025-01-12 11:30:00", "VIP"),
        ("Carol", "Williams", "carol.williams@example.com", "555-0103", "Chicago", "IL", "USA", "60601", "2025-01-15 14:20:00", "VIP"),
        ("David", "Brown", "david.brown@example.com", "555-0104", "Houston", "TX", "USA", "77001", "2025-01-18 16:45:00", "VIP"),
        ("Emma", "Jones", "emma.jones@example.com", "555-0105", "Seattle", "WA", "USA", "98101", "2025-01-20 10:10:00", "VIP"),
        ("Frank", "Garcia", "frank.garcia@example.com", "555-0106", "Austin", "TX", "USA", "73301", "2025-01-22 13:50:00", "VIP"),

        # Regular Customers (7 - 22)
        ("Grace", "Miller", "grace.miller@example.com", "555-0107", "Miami", "FL", "USA", "33101", "2025-02-01 08:30:00", "Regular"),
        ("Henry", "Davis", "henry.davis@example.com", "555-0108", "Denver", "CO", "USA", "80201", "2025-02-03 12:00:00", "Regular"),
        ("Ivy", "Rodriguez", "ivy.rodriguez@example.com", "555-0109", "Boston", "MA", "USA", "02101", "2025-02-05 15:40:00", "Regular"),
        ("Jack", "Martinez", "jack.martinez@example.com", "555-0110", "Atlanta", "GA", "USA", "30301", "2025-02-08 09:25:00", "Regular"),
        ("Karen", "Hernandez", "karen.hernandez@example.com", "555-0111", "San Francisco", "CA", "USA", "94101", "2025-02-10 11:15:00", "Regular"),
        ("Leo", "Lopez", "leo.lopez@example.com", "555-0112", "Phoenix", "AZ", "USA", "85001", "2025-02-12 14:05:00", "Regular"),
        ("Mia", "Gonzalez", "mia.gonzalez@example.com", "555-0113", "Philadelphia", "PA", "USA", "19101", "2025-02-15 16:30:00", "Regular"),
        ("Noah", "Wilson", "noah.wilson@example.com", "555-0114", "Dallas", "TX", "USA", "75201", "2025-02-18 10:45:00", "Regular"),
        ("Olivia", "Anderson", "olivia.anderson@example.com", "555-0115", "San Diego", "CA", "USA", "92101", "2025-02-20 13:20:00", "Regular"),
        ("Paul", "Thomas", "paul.thomas@example.com", "555-0116", "Portland", "OR", "USA", "97201", "2025-02-22 17:10:00", "Regular"),
        ("Quinn", "Taylor", "quinn.taylor@example.com", "555-0117", "Nashville", "TN", "USA", "37201", "2025-02-25 09:00:00", "Regular"),
        ("Ruby", "Moore", "ruby.moore@example.com", "555-0118", "Las Vegas", "NV", "USA", "89101", "2025-03-01 11:55:00", "Regular"),
        ("Sam", "Jackson", "sam.jackson@example.com", "555-0119", "Charlotte", "NC", "USA", "28201", "2025-03-03 14:40:00", "Regular"),
        ("Tara", "Martin", "tara.martin@example.com", "555-0120", "Detroit", "MI", "USA", "48201", "2025-03-05 16:15:00", "Regular"),
        ("Uma", "Lee", "uma.lee@example.com", "555-0121", "Minneapolis", "MN", "USA", "55401", "2025-03-08 10:30:00", "Regular"),
        ("Victor", "Perez", "victor.perez@example.com", "555-0122", "Tampa", "FL", "USA", "33601", "2025-03-10 13:10:00", "Regular"),

        # New Customers (23 - 27)
        ("Wendy", "White", "wendy.white@example.com", "555-0123", "Orlando", "FL", "USA", "32801", "2026-06-01 11:00:00", "New"),
        ("Xavier", "Harris", "xavier.harris@example.com", "555-0124", "Raleigh", "NC", "USA", "27601", "2026-06-15 15:30:00", "New"),
        ("Yara", "Clark", "yara.clark@example.com", "555-0125", "Salt Lake City", "UT", "USA", "84101", "2026-07-01 09:45:00", "New"),
        ("Zack", "Lewis", "zack.lewis@example.com", "555-0126", "Pittsburgh", "PA", "USA", "15201", "2026-07-10 14:15:00", "New"),
        ("Amber", "Robinson", "amber.robinson@example.com", "555-0127", "Indianapolis", "IN", "USA", "46201", "2026-07-20 16:00:00", "New"),

        # Inactive Customers (28 - 30) with 0 Orders (Edge cases for LEFT JOIN tests)
        ("Brian", "Walker", "brian.walker@example.com", "555-0128", "Kansas City", "MO", "USA", "64101", "2025-01-05 08:00:00", "Inactive"),
        ("Chloe", "Young", "chloe.young@example.com", "555-0129", "Columbus", "OH", "USA", "43201", "2025-01-08 12:30:00", "Inactive"),
        ("Derek", "Allen", "derek.allen@example.com", "555-0130", "Cleveland", "OH", "USA", "44101", "2025-01-09 17:20:00", "Inactive"),
    ]

    cursor.executemany(
        """
        INSERT INTO customers (first_name, last_name, email, phone, city, state, country, postal_code, created_at, customer_segment)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        customers_data
    )

    # 2. Seed Products (25 records across 5 categories)
    # Categories: Electronics, Apparel, Footwear, Home & Kitchen, Books & Media
    # Edge cases:
    #   - Products 24 & 25 have 0 order items (unsold)
    #   - Products 10 & 20 have stock_quantity = 0 (out of stock)
    products_data = [
        # Electronics (1 - 5)
        ("Wireless Noise-Canceling Headphones", "Electronics", 299.99, 140.00, 85, 4.8, 1),
        ("Ultra HD 4K Smart Monitor 27-inch", "Electronics", 399.99, 220.00, 42, 4.7, 1),
        ("Mechanical Gaming Keyboard RGB", "Electronics", 129.99, 60.00, 120, 4.6, 1),
        ("Ergonomic Wireless Mouse", "Electronics", 69.99, 28.00, 210, 4.5, 1),
        ("USB-C Multiport Hub Adapter", "Electronics", 49.99, 18.00, 350, 4.4, 1),

        # Apparel (6 - 10)
        ("Organic Cotton Crewneck T-Shirt", "Apparel", 29.99, 9.50, 450, 4.5, 1),
        ("Slim-Fit Denim Jeans", "Apparel", 79.99, 32.00, 180, 4.3, 1),
        ("Waterproof Windbreaker Jacket", "Apparel", 119.99, 52.00, 95, 4.6, 1),
        ("Merino Wool Thermal Sweater", "Apparel", 89.99, 38.00, 110, 4.7, 1),
        ("Breathable Athletic Shorts", "Apparel", 34.99, 12.00, 0, 4.2, 1), # Out of stock

        # Footwear (11 - 15)
        ("Pro Lightweight Running Shoes", "Footwear", 139.99, 62.00, 140, 4.8, 1),
        ("Classic Leather Dress Shoes", "Footwear", 159.99, 75.00, 70, 4.6, 1),
        ("All-Weather Hiking Boots", "Footwear", 189.99, 85.00, 60, 4.9, 1),
        ("Comfort Slip-On Canvas Loafers", "Footwear", 59.99, 22.00, 160, 4.3, 1),
        ("Memory Foam Indoor Slippers", "Footwear", 29.99, 10.00, 230, 4.4, 1),

        # Home & Kitchen (16 - 20)
        ("Stainless Steel Espresso Machine", "Home & Kitchen", 499.99, 260.00, 30, 4.9, 1),
        ("Cast Iron Dutch Oven 6-Quart", "Home & Kitchen", 89.99, 38.00, 90, 4.8, 1),
        ("Precision Digital Kitchen Scale", "Home & Kitchen", 24.99, 8.50, 280, 4.6, 1),
        ("Chef's High-Carbon Knife Set 8pc", "Home & Kitchen", 149.99, 65.00, 55, 4.7, 1),
        ("Double-Wall Insulated Travel Tumbler", "Home & Kitchen", 19.99, 6.00, 0, 4.3, 1), # Out of stock

        # Books & Media (21 - 25)
        ("Designing Data-Intensive Applications", "Books & Media", 44.99, 18.00, 175, 4.9, 1),
        ("Modern Data Engineering with Python", "Books & Media", 49.99, 20.00, 130, 4.7, 1),
        ("Clean Architecture Handbook", "Books & Media", 39.99, 15.00, 190, 4.8, 1),
        ("Rare Vintage Astronomy Atlas (1st Ed)", "Books & Media", 299.99, 150.00, 5, 4.1, 1), # Unsold product (0 order items)
        ("Legacy Cobol Systems Manual (Collector)", "Books & Media", 79.99, 30.00, 12, 3.8, 0), # Unsold & inactive
    ]

    cursor.executemany(
        """
        INSERT INTO products (product_name, category, price, cost, stock_quantity, rating, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        products_data
    )

    # 3. Seed Orders & Order Items
    # Target: exactly 75 orders, exactly 180 order_items.
    # Customers 1 to 27 will have orders. Customers 28 to 30 will have 0 orders.
    # Products 1 to 23 will be used in order items. Products 24 & 25 will have 0 items.

    # Order count allocation across 27 active customers to sum to exactly 75 orders:
    # - 6 VIPs (cust 1-6): [6, 6, 5, 5, 5, 5] = 32 orders
    # - 16 Regulars (cust 7-22): [3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3] = 38 orders
    # - 5 News (cust 23-27): [1, 1, 1, 1, 1] = 5 orders
    # Total = 32 + 38 + 5 = 75 orders.
    order_allocations = [
        # VIPs (cust 1-6)
        (1, 6), (2, 6), (3, 5), (4, 5), (5, 5), (6, 5),
        # Regulars (cust 7-22)
        (7, 3), (8, 3), (9, 3), (10, 3), (11, 3), (12, 2), (13, 2), (14, 2),
        (15, 2), (16, 2), (17, 2), (18, 2), (19, 2), (20, 2), (21, 2), (22, 3),
        # News (cust 23-27)
        (23, 1), (24, 1), (25, 1), (26, 1), (27, 1),
    ]

    # Order item count allocation across 75 orders to sum to exactly 180 items:
    # 75 orders:
    # - 35 orders with 3 items = 105 items
    # - 35 orders with 2 items = 70 items
    # - 5 orders with 1 item = 5 items
    # Total items = 105 + 70 + 5 = 180 items!
    item_counts_per_order = [3] * 35 + [2] * 35 + [1] * 5

    # Deterministic product catalog reference (id -> price)
    product_prices = {i + 1: products_data[i][2] for i in range(25)}

    # 75 order statuses: 50 Delivered, 12 Shipped, 5 Processing, 4 Pending, 4 Cancelled
    statuses = (
        ["Delivered"] * 50 +
        ["Shipped"] * 12 +
        ["Processing"] * 5 +
        ["Pending"] * 4 +
        ["Cancelled"] * 4
    )

    payment_methods_pool = ["Credit Card", "PayPal", "Apple Pay", "Debit Card", "Bank Transfer"]

    # Pre-map customer shipping locations
    customer_locations = {
        i + 1: (customers_data[i][4], customers_data[i][5])
        for i in range(30)
    }

    # Build order records
    order_records = []
    order_id_counter = 1

    # Date generation parameters
    base_dates = [
        f"2025-{m:02d}-{d:02d} {h:02d}:{min:02d}:00"
        for m in range(1, 13)
        for d in [5, 12, 19, 26]
        for h in [10, 14]
        for min in [15, 45]
    ] + [
        f"2026-{m:02d}-{d:02d} {h:02d}:{min:02d}:00"
        for m in range(1, 8)
        for d in [3, 10, 17, 24]
        for h in [11, 16]
        for min in [20, 50]
    ]

    date_idx = 0
    for cust_id, num_orders in order_allocations:
        for _ in range(num_orders):
            order_date = base_dates[date_idx % len(base_dates)]
            date_idx += 3
            status = statuses[order_id_counter - 1]
            ship_city, ship_state = customer_locations[cust_id]
            payment_method = payment_methods_pool[(order_id_counter * 3 + cust_id) % len(payment_methods_pool)]

            order_records.append({
                "order_id": order_id_counter,
                "customer_id": cust_id,
                "order_date": order_date,
                "status": status,
                "shipping_city": ship_city,
                "shipping_state": ship_state,
                "total_amount": 0.0, # Will calculate from items
                "payment_method": payment_method
            })
            order_id_counter += 1

    # Build order items (exactly 180 records)
    order_items_records = []
    item_id_counter = 1
    discount_pool = [0.0, 0.0, 0.0, 0.0, 0.05, 0.10, 0.15, 0.20]

    for order_idx, num_items in enumerate(item_counts_per_order):
        order_id = order_idx + 1
        raw_order_total = 0.0

        # Pick distinct products for this order from products 1 to 23 (leaving 24 and 25 unsold)
        # Choose products deterministically based on order_id
        start_prod = ((order_id * 7) % 23) + 1

        for item_offset in range(num_items):
            prod_id = ((start_prod + item_offset * 3 - 1) % 23) + 1
            unit_price = product_prices[prod_id]

            # Deterministic quantity: 1 to 4 units
            qty = ((order_id + item_offset * 2) % 4) + 1

            # Deterministic discount
            disc = discount_pool[(order_id + item_offset) % len(discount_pool)]

            raw_subtotal = qty * unit_price * (1.0 - disc)
            raw_order_total += raw_subtotal

            order_items_records.append((
                item_id_counter,
                order_id,
                prod_id,
                qty,
                unit_price,
                disc
            ))
            item_id_counter += 1

        order_records[order_idx]["total_amount"] = round(raw_order_total, 2)

    # Insert orders
    cursor.executemany(
        """
        INSERT INTO orders (order_id, customer_id, order_date, status, shipping_city, shipping_state, total_amount, payment_method)
        VALUES (:order_id, :customer_id, :order_date, :status, :shipping_city, :shipping_state, :total_amount, :payment_method);
        """,
        order_records
    )

    # Insert order items
    cursor.executemany(
        """
        INSERT INTO order_items (item_id, order_id, product_id, quantity, unit_price, discount)
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        order_items_records
    )

    conn.commit()


def init_db(db_path: str = "ecommerce.db", force: bool = False) -> str:
    """
    Initializes the database schema and populates deterministic seed data.
    If force=False and tables are already populated, schema creation is idempotent.
    Returns the resolved string path of the database.
    """
    resolved = get_resolved_db_path(db_path)

    # Ensure parent directory exists
    resolved.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(resolved), timeout=10.0)
    try:
        # Create schema tables and indexes
        conn.executescript(SCHEMA_DDL)
        conn.commit()

        # Check existing row counts
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM customers;")
        cust_count = cursor.fetchone()[0]

        if force or cust_count == 0:
            seed_database(conn)

        return str(resolved)
    finally:
        conn.close()


def reset_database(db_path: str = "ecommerce.db") -> str:
    """
    Wipes all existing records and re-seeds the database with standard mock data.
    Ensures exact row counts: 30 customers, 25 products, 75 orders, 180 order_items.
    """
    return init_db(db_path=db_path, force=True)

