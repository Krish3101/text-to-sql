-- Enable foreign key constraints
PRAGMA foreign_keys = ON;

-- Column comments stay inside CREATE TABLE so SQLite keeps them in sqlite_master,
-- which is what the model sees as the schema.

-- 1. Customers Table
CREATE TABLE IF NOT EXISTS customers (
    customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT,
    city TEXT NOT NULL,
    state TEXT NOT NULL, -- two-letter US state code
    country TEXT NOT NULL DEFAULT 'USA',
    postal_code TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, -- signup time, text 'YYYY-MM-DD HH:MM:SS'
    customer_segment TEXT NOT NULL DEFAULT 'Regular' CHECK(customer_segment IN ('VIP', 'Regular', 'New', 'Inactive'))
);

-- 2. Products Table
CREATE TABLE IF NOT EXISTS products (
    product_id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL,
    price REAL NOT NULL CHECK(price >= 0), -- current retail price in USD
    cost REAL NOT NULL CHECK(cost >= 0), -- wholesale cost in USD; profit per unit = price - cost
    stock_quantity INTEGER NOT NULL DEFAULT 0 CHECK(stock_quantity >= 0), -- units in stock now
    rating REAL CHECK(rating >= 0.0 AND rating <= 5.0), -- average review score
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)) -- 1 = on sale, 0 = discontinued
);

-- 3. Orders Table
CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    order_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, -- text 'YYYY-MM-DD HH:MM:SS'
    status TEXT NOT NULL CHECK(status IN ('Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled', 'Refunded')), -- 'Delivered' means completed
    shipping_city TEXT,
    shipping_state TEXT,
    total_amount REAL NOT NULL DEFAULT 0.0 CHECK(total_amount >= 0), -- stored order total, rounded to cents
    payment_method TEXT CHECK(payment_method IN ('Credit Card', 'PayPal', 'Debit Card', 'Apple Pay', 'Bank Transfer')),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id) ON DELETE RESTRICT
);

-- 4. Order Items Table
CREATE TABLE IF NOT EXISTS order_items (
    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_price REAL NOT NULL CHECK(unit_price >= 0), -- price per unit when the order was placed
    discount REAL NOT NULL DEFAULT 0.0 CHECK(discount >= 0.0 AND discount <= 1.0), -- fraction off, 0.10 = 10% off
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
