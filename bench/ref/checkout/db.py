import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    customer TEXT NOT NULL,
    email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    sku TEXT NOT NULL,
    qty INTEGER NOT NULL,
    price_cents INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS items_order_id ON items(order_id);
CREATE TABLE IF NOT EXISTS coupons (
    code TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    value INTEGER NOT NULL,
    min_total_cents INTEGER NOT NULL DEFAULT 0,
    expires_on TEXT,
    max_redemptions INTEGER
);
CREATE TABLE IF NOT EXISTS redemptions (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL REFERENCES coupons(code),
    order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id),
    discount_cents INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def connect(path=":memory:"):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def save_order(conn, customer, email, items):
    cur = conn.execute(
        "INSERT INTO orders (customer, email) VALUES (?, ?)",
        (customer, email),
    )
    order_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO items (order_id, sku, qty, price_cents) VALUES (?, ?, ?, ?)",
        [(order_id, i["sku"], i["qty"], i["price_cents"]) for i in items],
    )
    conn.commit()
    return order_id
