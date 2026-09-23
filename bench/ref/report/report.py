import datetime
import re

TOP_SKUS = 5

_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def parse_date(value):
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise ValueError(f"invalid date: {value!r}")
    return datetime.date.fromisoformat(value)


def order_report(conn, start, end):
    """Orders whose created_at date (UTC) falls in [start, end], both inclusive."""
    if parse_date(start) > parse_date(end):
        raise ValueError("start is after end")
    rows = conn.execute(
        "SELECT email, COUNT(*) AS orders, SUM(total) AS revenue_cents FROM ("
        " SELECT o.email, COALESCE(SUM(i.qty * i.price_cents), 0) AS total"
        " FROM orders o LEFT JOIN items i ON i.order_id = o.id"
        " WHERE date(o.created_at) BETWEEN ? AND ? GROUP BY o.id"
        ") GROUP BY email ORDER BY revenue_cents DESC, email ASC",
        (start, end),
    ).fetchall()
    customers = [dict(r) for r in rows]
    skus = conn.execute(
        "SELECT i.sku, SUM(i.qty) AS qty FROM items i JOIN orders o ON o.id = i.order_id"
        " WHERE date(o.created_at) BETWEEN ? AND ?"
        " GROUP BY i.sku ORDER BY qty DESC, i.sku ASC LIMIT ?",
        (start, end, TOP_SKUS),
    ).fetchall()
    return {
        "orders": sum(c["orders"] for c in customers),
        "revenue_cents": sum(c["revenue_cents"] for c in customers),
        "customers": customers,
        "top_skus": [dict(r) for r in skus],
    }
