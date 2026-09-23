import re
import sqlite3

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$")
REGIONS = ("US-CA", "US-NY", "DE", "GB", "IN")


class CustomerError(Exception):
    pass


def normalize_email(email: str) -> str:
    """Email addresses are case-insensitive here: strip surrounding blanks and lower-case."""
    return email.strip().lower()


def create_customer(conn, email, name, region):
    """Store a customer and return its id. Raises CustomerError for an invalid email, an empty
    name, an unknown region, or an email that is already registered (in any letter case)."""
    if not isinstance(email, str) or not EMAIL_RE.match(email := normalize_email(email)):
        raise CustomerError("invalid email")
    if not isinstance(name, str) or not name.strip():
        raise CustomerError("name required")
    if not isinstance(region, str) or region not in REGIONS:
        raise CustomerError("unknown region")
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO customers (email, name, region) VALUES (?, ?, ?)",
                (email, name.strip(), region),
            )
    except sqlite3.IntegrityError:
        raise CustomerError("email already registered") from None
    return cur.lastrowid


def get_customer(conn, customer_id):
    row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    return dict(row) if row else None


def find_by_email(conn, email):
    row = conn.execute(
        "SELECT * FROM customers WHERE email = ?", (normalize_email(email),)
    ).fetchone()
    return dict(row) if row else None


def open_invoices(conn, customer_id):
    """Open invoices of one customer, oldest first, as a list of dicts."""
    return [dict(row) for row in conn.execute(
        "SELECT id, number, total_cents FROM invoices"
        " WHERE customer_id = ? AND status = 'open' ORDER BY id",
        (customer_id,),
    )]


def may_act_for(actor, email: str) -> bool:
    """Staff may act for anyone; a customer only for themself (email in any letter case)."""
    if not isinstance(actor, str):
        return False
    return actor.startswith("staff:") or normalize_email(actor) == normalize_email(email)
