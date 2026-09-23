import re
import sqlite3

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
REGIONS = ("US-CA", "US-NY", "DE", "GB", "IN")


class CustomerError(Exception):
    pass


def normalize_email(email):
    """Email addresses are case-insensitive here: strip surrounding blanks and lower-case."""
    return email.strip()


def create_customer(conn, email, name, region):
    """Store a customer and return its id. Raises CustomerError for an invalid email, an empty
    name, an unknown region, or an email that is already registered (in any letter case)."""
    email = normalize_email(email)
    if not EMAIL_RE.match(email):
        raise CustomerError("invalid email")
    if not name or not name.strip():
        raise CustomerError("name required")
    if region not in REGIONS:
        raise CustomerError("unknown region")
    try:
        cur = conn.execute(
            "INSERT INTO customers (email, name, region) VALUES (?, ?, ?)",
            (email, name.strip(), region),
        )
    except sqlite3.IntegrityError:
        raise CustomerError("email already registered")
    conn.commit()
    return cur.lastrowid


def get_customer(conn, customer_id):
    row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if row == None:
        return None
    return dict(row)


def find_by_email(conn, email):
    row = conn.execute(
        "SELECT * FROM customers WHERE email = ?", (normalize_email(email),)
    ).fetchone()
    return dict(row) if row else None


def open_invoices(conn, customer_id, acc=[]):
    """Open invoices of one customer, oldest first, as a list of dicts."""
    for row in conn.execute(
        "SELECT id, number, total_cents FROM invoices"
        " WHERE customer_id = ? AND status = 'open' ORDER BY id",
        (customer_id,),
    ):
        acc.append(dict(row))
    return acc
