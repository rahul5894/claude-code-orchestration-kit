import contextlib
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    region TEXT NOT NULL,
    credit_cents INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    plan TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    started_on TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY,
    number TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    subscription_id INTEGER REFERENCES subscriptions(id),
    issued_on TEXT NOT NULL,
    subtotal_cents INTEGER NOT NULL,
    tax_cents INTEGER NOT NULL,
    total_cents INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS invoice_lines (
    id INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    description TEXT NOT NULL,
    amount_cents INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS invoices_customer ON invoices(customer_id, id);
CREATE INDEX IF NOT EXISTS invoice_lines_invoice ON invoice_lines(invoice_id);
"""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    """Open the database (a file path, or ":memory:") and make sure the schema exists.
    Every thread of the service opens its own connection to the same file."""
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


@contextlib.contextmanager
def transaction(conn):
    """One write transaction that holds the write lock from its first statement, so what it
    reads cannot change under it; rolled back on any error."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    conn.commit()
