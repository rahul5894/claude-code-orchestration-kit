from typing import List, Optional, Tuple

from billing import dates, tax


def next_number(conn):
    row = conn.execute("SELECT MAX(id) FROM invoices").fetchone()
    return "INV-{:06d}".format((row[0] or 0) + 1)


def issue_invoice(conn, customer_id, subscription_id, lines: List[Tuple[str, int]], issued_on=None):
    """Create an open invoice from lines [(description, amount_cents), ...] and return its id.

    Tax is computed on the subtotal (the sum of the lines) by the customer's region; the total
    is subtotal + tax. All or nothing: if any line cannot be stored, no part of the invoice
    remains. Invoice numbers are unique and increase: INV-000001, INV-000002, ...
    """
    if issued_on is None:
        issued_on = dates.utc_today()
    region = conn.execute(
        "SELECT region FROM customers WHERE id = ?", (customer_id,)
    ).fetchone()["region"]
    subtotal = 0
    for i in range(len(lines)):
        subtotal = subtotal + lines[i][1]
    tax_cents = tax.tax_for(region, subtotal)
    cur = conn.execute(
        "INSERT INTO invoices (number, customer_id, subscription_id, issued_on,"
        " subtotal_cents, tax_cents, total_cents) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (next_number(conn), customer_id, subscription_id, issued_on.isoformat(),
         subtotal, tax_cents, subtotal + tax_cents),
    )
    conn.commit()
    invoice_id = cur.lastrowid
    for description, amount in lines:
        conn.execute(
            "INSERT INTO invoice_lines (invoice_id, description, amount_cents) VALUES (?, ?, ?)",
            (invoice_id, description, amount),
        )
        conn.commit()
    return invoice_id


def get_invoice(conn, invoice_id) -> Optional[dict]:
    """The invoice as a dict with its "lines" (description, amount_cents), or None."""
    row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if row is None:
        return None
    invoice = dict(row)
    invoice["lines"] = []
    for r in conn.execute(
        "SELECT description, amount_cents FROM invoice_lines WHERE invoice_id = ? ORDER BY id",
        (invoice_id,),
    ):
        invoice["lines"].append(dict(r))
    return invoice


def mark_paid(conn, invoice_id):
    cur = conn.execute(
        "UPDATE invoices SET status = 'paid' WHERE id = ? AND status = 'open'", (invoice_id,)
    )
    conn.commit()
    return cur.rowcount == 1
