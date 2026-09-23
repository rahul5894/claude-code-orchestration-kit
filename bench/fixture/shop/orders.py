import threading

PAGE_SIZE = 20
STATUSES = ("new", "paid", "shipped", "cancelled")

_SORT_COLUMNS = {
    "newest": "created_at DESC, id DESC",
    "oldest": "created_at ASC, id ASC",
    "customer": "customer ASC, id ASC",
}

_customer_cache = {}
_cache_lock = threading.Lock()


def get_order(conn, order_id):
    row = conn.execute(
        "SELECT id, customer, email, status, created_at FROM orders WHERE id = ?",
        (order_id,),
    ).fetchone()
    return dict(row) if row else None


def search(conn, term):
    rows = conn.execute(
        "SELECT id, customer, email, status FROM orders WHERE customer LIKE ?",
        (f"%{term}%",),
    ).fetchall()
    return [dict(r) for r in rows]


def list_page(conn, page=1, size=PAGE_SIZE):
    """Return one page of orders, newest first. Pages are numbered from 1."""
    if page < 1 or size < 1:
        raise ValueError("page and size must be positive")
    rows = conn.execute(
        "SELECT id, customer, status FROM orders ORDER BY id DESC LIMIT ? OFFSET ?",
        (size, (page - 1) * size),
    ).fetchall()
    return [dict(r) for r in rows]


def sort_orders(conn, column):
    try:
        order_by = _SORT_COLUMNS[column]
    except KeyError:
        raise ValueError(f"unknown sort column: {column}") from None
    rows = conn.execute(
        f"SELECT id, customer, created_at FROM orders ORDER BY {order_by}"
    ).fetchall()
    return [dict(r) for r in rows]


def set_status(conn, order_id, status):
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status}")
    cur = conn.execute(
        "UPDATE orders SET status = ? WHERE id = ?", (status, order_id)
    )
    conn.commit()
    return cur.rowcount == 1


def add_item(order, item, tags=None):
    tags = [] if tags is None else tags
    tags.append(item["sku"])
    order.setdefault("items", []).append(item)
    order["tags"] = tags
    return order


def order_totals(conn):
    rows = conn.execute(
        "SELECT o.id, COALESCE(SUM(i.qty * i.price_cents), 0) AS total"
        " FROM orders o LEFT JOIN items i ON i.order_id = o.id GROUP BY o.id"
    ).fetchall()
    return {r["id"]: r["total"] for r in rows}


def customer_of(conn, order_id):
    with _cache_lock:
        if order_id not in _customer_cache:
            row = conn.execute(
                "SELECT customer FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
            _customer_cache[order_id] = row["customer"] if row else None
        return _customer_cache[order_id]
