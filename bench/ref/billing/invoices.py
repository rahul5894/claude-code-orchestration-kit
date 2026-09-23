import datetime

from billing import dates, db, tax


def next_number(conn) -> str:
    return number_for(next_id(conn))


def next_id(conn) -> int:
    return conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM invoices").fetchone()[0]


def number_for(invoice_id: int) -> str:
    return f"INV-{invoice_id:06d}"


def insert_invoice(conn, invoice_id, customer_id, subscription_id, region,
                   lines: list[tuple[str, int]], issued_on: datetime.date) -> int:
    """Store one invoice with an id the caller reserved. Runs inside the caller's transaction."""
    subtotal = sum(amount for _, amount in lines)
    tax_cents = tax.tax_for(region, subtotal)
    conn.execute(
        "INSERT INTO invoices (id, number, customer_id, subscription_id, issued_on,"
        " subtotal_cents, tax_cents, total_cents) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (invoice_id, number_for(invoice_id), customer_id, subscription_id,
         issued_on.isoformat(), subtotal, tax_cents, subtotal + tax_cents),
    )
    conn.executemany(
        "INSERT INTO invoice_lines (invoice_id, description, amount_cents) VALUES (?, ?, ?)",
        [(invoice_id, description, amount) for description, amount in lines],
    )
    return invoice_id


def issue_invoice(conn, customer_id, subscription_id, lines: list[tuple[str, int]],
                  issued_on=None):
    """Create an open invoice from lines [(description, amount_cents), ...] and return its id.

    Tax is computed on the subtotal (the sum of the lines) by the customer's region; the total
    is subtotal + tax. All or nothing: if any line cannot be stored, no part of the invoice
    remains. Invoice numbers are unique and increase: INV-000001, INV-000002, ...
    """
    with db.transaction(conn):
        region = conn.execute(
            "SELECT region FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()["region"]
        return insert_invoice(conn, next_id(conn), customer_id, subscription_id, region,
                              lines, issued_on or dates.utc_today())


def get_invoice(conn, invoice_id) -> dict | None:
    """The invoice as a dict with its "lines" (description, amount_cents), or None."""
    row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if row is None:
        return None
    invoice = dict(row)
    invoice["lines"] = [dict(r) for r in conn.execute(
        "SELECT description, amount_cents FROM invoice_lines WHERE invoice_id = ? ORDER BY id",
        (invoice_id,),
    )]
    return invoice


def mark_paid(conn, invoice_id):
    with conn:
        cur = conn.execute(
            "UPDATE invoices SET status = 'paid' WHERE id = ? AND status = 'open'", (invoice_id,)
        )
    return cur.rowcount == 1


def statement_page(conn, customer_id: int, limit: int, before_id: int | None) -> list[dict]:
    """Up to `limit` invoices of a customer with id < before_id, highest id first."""
    return [dict(r) for r in conn.execute(
        "SELECT id, number, issued_on, total_cents, status FROM invoices"
        " WHERE customer_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
        (customer_id, before_id if before_id is not None else 2**63 - 1, limit),
    )]
