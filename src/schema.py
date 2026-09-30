"""
E-Commerce Database Schema Definitions and Introspection Helpers.

Defines the relational schema for 4 interconnected tables (customers, products, orders, order_items),
including primary/foreign keys, check constraints, performance indexes, and prompt formatting helpers.
"""

from typing import Any

SCHEMA_DDL = """
-- Enable foreign key constraints
PRAGMA foreign_keys = ON;

-- 1. Customers Table
CREATE TABLE IF NOT EXISTS customers (
    customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT 'USA',
    postal_code TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    customer_segment TEXT NOT NULL DEFAULT 'Regular' CHECK(customer_segment IN ('VIP', 'Regular', 'New', 'Inactive'))
);

-- 2. Products Table
CREATE TABLE IF NOT EXISTS products (
    product_id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL,
    price REAL NOT NULL CHECK(price >= 0),
    cost REAL NOT NULL CHECK(cost >= 0),
    stock_quantity INTEGER NOT NULL DEFAULT 0 CHECK(stock_quantity >= 0),
    rating REAL CHECK(rating >= 0.0 AND rating <= 5.0),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1))
);

-- 3. Orders Table
CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    order_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL CHECK(status IN ('Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled', 'Refunded')),
    shipping_city TEXT,
    shipping_state TEXT,
    total_amount REAL NOT NULL DEFAULT 0.0 CHECK(total_amount >= 0),
    payment_method TEXT CHECK(payment_method IN ('Credit Card', 'PayPal', 'Debit Card', 'Apple Pay', 'Bank Transfer')),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id) ON DELETE RESTRICT
);

-- 4. Order Items Table
CREATE TABLE IF NOT EXISTS order_items (
    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_price REAL NOT NULL CHECK(unit_price >= 0),
    discount REAL NOT NULL DEFAULT 0.0 CHECK(discount >= 0.0 AND discount <= 1.0),
    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE RESTRICT
);

-- Query Performance & Join Indexes
CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_order_date ON orders(order_date);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product_id ON order_items(product_id);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_customers_city_state ON customers(city, state);
CREATE INDEX IF NOT EXISTS idx_customers_segment ON customers(customer_segment);
"""

TABLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "customers": {
        "description": "Stores user demographics, contact info, geographical location, and segment classification.",
        "primary_key": "customer_id",
        "foreign_keys": [],
        "columns": [
            {
                "name": "customer_id",
                "type": "INTEGER",
                "description": "Primary key, unique customer identifier",
            },
            {"name": "first_name", "type": "TEXT", "description": "Customer given name"},
            {"name": "last_name", "type": "TEXT", "description": "Customer family name"},
            {"name": "email", "type": "TEXT", "description": "Unique contact email address"},
            {"name": "phone", "type": "TEXT", "description": "Contact phone number (nullable)"},
            {"name": "city", "type": "TEXT", "description": "Customer billing/residence city"},
            {
                "name": "state",
                "type": "TEXT",
                "description": "Two-letter US state code or state name",
            },
            {
                "name": "country",
                "type": "TEXT",
                "description": "Country code or name, default 'USA'",
            },
            {"name": "postal_code", "type": "TEXT", "description": "Postal or ZIP code"},
            {
                "name": "created_at",
                "type": "TIMESTAMP",
                "description": "Account registration timestamp (ISO format)",
            },
            {
                "name": "customer_segment",
                "type": "TEXT",
                "description": "Customer tier: 'VIP', 'Regular', 'New', 'Inactive'",
            },
        ],
    },
    "products": {
        "description": "Catalog of merchandise, category classification, inventory levels, cost, and selling price.",
        "primary_key": "product_id",
        "foreign_keys": [],
        "columns": [
            {
                "name": "product_id",
                "type": "INTEGER",
                "description": "Primary key, unique product identifier",
            },
            {"name": "product_name", "type": "TEXT", "description": "Merchandise title/name"},
            {
                "name": "category",
                "type": "TEXT",
                "description": "Product category (Electronics, Apparel, Footwear, Home & Kitchen, Books & Media)",
            },
            {"name": "price", "type": "REAL", "description": "Retail selling price in USD (>= 0)"},
            {
                "name": "cost",
                "type": "REAL",
                "description": "Wholesale acquisition cost in USD (>= 0)",
            },
            {
                "name": "stock_quantity",
                "type": "INTEGER",
                "description": "Current inventory stock on hand (>= 0)",
            },
            {
                "name": "rating",
                "type": "REAL",
                "description": "Average review rating from 0.0 to 5.0",
            },
            {
                "name": "is_active",
                "type": "INTEGER",
                "description": "Availability flag: 1 if active, 0 if discontinued",
            },
        ],
    },
    "orders": {
        "description": "Header records for customer purchase transactions, timestamps, delivery statuses, and totals.",
        "primary_key": "order_id",
        "foreign_keys": [
            {
                "column": "customer_id",
                "references_table": "customers",
                "references_column": "customer_id",
            }
        ],
        "columns": [
            {
                "name": "order_id",
                "type": "INTEGER",
                "description": "Primary key, unique order identifier",
            },
            {
                "name": "customer_id",
                "type": "INTEGER",
                "description": "Foreign key referencing customers.customer_id",
            },
            {
                "name": "order_date",
                "type": "TIMESTAMP",
                "description": "Order placement timestamp (ISO format)",
            },
            {
                "name": "status",
                "type": "TEXT",
                "description": "Order lifecycle status: 'Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled', 'Refunded'",
            },
            {
                "name": "shipping_city",
                "type": "TEXT",
                "description": "Destination city for shipping",
            },
            {
                "name": "shipping_state",
                "type": "TEXT",
                "description": "Destination state for shipping",
            },
            {
                "name": "total_amount",
                "type": "REAL",
                "description": "Total order charge in USD after discounts (>= 0)",
            },
            {
                "name": "payment_method",
                "type": "TEXT",
                "description": "Payment method used: 'Credit Card', 'PayPal', 'Debit Card', 'Apple Pay', 'Bank Transfer'",
            },
        ],
    },
    "order_items": {
        "description": "Line item breakdown for each order, tracking products purchased, quantities, unit prices, and discounts.",
        "primary_key": "item_id",
        "foreign_keys": [
            {"column": "order_id", "references_table": "orders", "references_column": "order_id"},
            {
                "column": "product_id",
                "references_table": "products",
                "references_column": "product_id",
            },
        ],
        "columns": [
            {
                "name": "item_id",
                "type": "INTEGER",
                "description": "Primary key, unique line item identifier",
            },
            {
                "name": "order_id",
                "type": "INTEGER",
                "description": "Foreign key referencing orders.order_id",
            },
            {
                "name": "product_id",
                "type": "INTEGER",
                "description": "Foreign key referencing products.product_id",
            },
            {"name": "quantity", "type": "INTEGER", "description": "Units purchased (> 0)"},
            {
                "name": "unit_price",
                "type": "REAL",
                "description": "Unit sale price at time of purchase (>= 0)",
            },
            {
                "name": "discount",
                "type": "REAL",
                "description": "Discount fraction applied (0.0 to 1.0)",
            },
        ],
    },
}

RELATIONSHIPS: list[dict[str, str]] = [
    {
        "from_table": "orders",
        "from_column": "customer_id",
        "to_table": "customers",
        "to_column": "customer_id",
        "type": "Many-to-One",
        "description": "Each order belongs to exactly one customer. A customer can place zero or more orders.",
    },
    {
        "from_table": "order_items",
        "from_column": "order_id",
        "to_table": "orders",
        "to_column": "order_id",
        "type": "Many-to-One",
        "description": "Each order item belongs to exactly one order. An order consists of one or more order items.",
    },
    {
        "from_table": "order_items",
        "from_column": "product_id",
        "to_table": "products",
        "to_column": "product_id",
        "type": "Many-to-One",
        "description": "Each order item references a product. A product can appear in multiple order items.",
    },
]


def get_erd_data() -> dict[str, Any]:
    """Returns structured metadata for Streamlit ERD and Schema explorer."""
    return {
        "tables": TABLE_DEFINITIONS,
        "relationships": RELATIONSHIPS,
    }


def get_schema_prompt_text() -> str:
    """
    Returns a concise, structured DDL and relational schema documentation
    suitable for injecting into LLM system prompts.
    """
    lines = [
        "DATABASE SCHEMA (SQLite 3):",
        "",
        "TABLE: customers",
        "  - customer_id (INTEGER, PRIMARY KEY AUTOINCREMENT)",
        "  - first_name (TEXT, NOT NULL)",
        "  - last_name (TEXT, NOT NULL)",
        "  - email (TEXT, NOT NULL UNIQUE)",
        "  - phone (TEXT)",
        "  - city (TEXT, NOT NULL)",
        "  - state (TEXT, NOT NULL)",
        "  - country (TEXT, NOT NULL DEFAULT 'USA')",
        "  - postal_code (TEXT)",
        "  - created_at (TIMESTAMP, NOT NULL)",
        "  - customer_segment (TEXT, CHECK IN ('VIP', 'Regular', 'New', 'Inactive'))",
        "",
        "TABLE: products",
        "  - product_id (INTEGER, PRIMARY KEY AUTOINCREMENT)",
        "  - product_name (TEXT, NOT NULL)",
        "  - category (TEXT, NOT NULL - e.g. 'Electronics', 'Apparel', 'Footwear', 'Home & Kitchen', 'Books & Media')",
        "  - price (REAL, NOT NULL, retail price)",
        "  - cost (REAL, NOT NULL, wholesale cost)",
        "  - stock_quantity (INTEGER, NOT NULL)",
        "  - rating (REAL, 0.0 to 5.0)",
        "  - is_active (INTEGER, 1 or 0)",
        "",
        "TABLE: orders",
        "  - order_id (INTEGER, PRIMARY KEY AUTOINCREMENT)",
        "  - customer_id (INTEGER, NOT NULL, FOREIGN KEY -> customers.customer_id)",
        "  - order_date (TIMESTAMP, NOT NULL)",
        "  - status (TEXT, CHECK IN ('Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled', 'Refunded'))",
        "  - shipping_city (TEXT)",
        "  - shipping_state (TEXT)",
        "  - total_amount (REAL, NOT NULL, total price after item discounts)",
        "  - payment_method (TEXT, CHECK IN ('Credit Card', 'PayPal', 'Debit Card', 'Apple Pay', 'Bank Transfer'))",
        "",
        "TABLE: order_items",
        "  - item_id (INTEGER, PRIMARY KEY AUTOINCREMENT)",
        "  - order_id (INTEGER, NOT NULL, FOREIGN KEY -> orders.order_id)",
        "  - product_id (INTEGER, NOT NULL, FOREIGN KEY -> products.product_id)",
        "  - quantity (INTEGER, NOT NULL)",
        "  - unit_price (REAL, NOT NULL, price per unit at purchase time)",
        "  - discount (REAL, NOT NULL DEFAULT 0.0, e.g. 0.10 for 10% off)",
        "",
        "FOREIGN KEY RELATIONSHIPS:",
        "  - orders.customer_id = customers.customer_id",
        "  - order_items.order_id = orders.order_id",
        "  - order_items.product_id = products.product_id",
        "",
        "KEY DOMAIN RULES & CALCULATIONS:",
        "  - Line Item Revenue = order_items.quantity * order_items.unit_price * (1 - order_items.discount)",
        "  - Profit per Product = products.price - products.cost",
        "  - An order total equals the sum of its order_items line amounts.",
        "  - To find customers with zero orders, use LEFT JOIN orders ON customers.customer_id = orders.customer_id WHERE orders.order_id IS NULL.",
        "  - To find unsold products, use LEFT JOIN order_items ON products.product_id = order_items.product_id WHERE order_items.item_id IS NULL.",
    ]
    return "\n".join(lines)
