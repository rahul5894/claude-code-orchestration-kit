import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS refunds (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    idempotency_key TEXT NOT NULL UNIQUE,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_lock = threading.Lock()
MAX_TEXT_LEN = 255


class RefundError(Exception):
    pass


def _as_result(row):
    return {
        "refund_id": row["id"],
        "order_id": row["order_id"],
        "amount_cents": row["amount_cents"],
        "status": "refunded",
    }


def _text_ok(value):
    if not isinstance(value, str) or not 0 < len(value) <= MAX_TEXT_LEN:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def refund(conn, order_id, amount_cents, idempotency_key, actor):
    if isinstance(order_id, bool) or not isinstance(order_id, int) or not 0 < order_id < 2**63:
        raise RefundError(f"unknown order: {order_id!r}")
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
        raise RefundError("amount_cents must be an integer")
    if amount_cents <= 0:
        raise RefundError("amount_cents must be positive")
    if not _text_ok(idempotency_key):
        raise RefundError("idempotency_key is required (at most 255 characters)")
    if not _text_ok(actor):
        raise RefundError("not allowed to refund this order")
    with _lock:
        conn.execute(SCHEMA)
        conn.execute("BEGIN IMMEDIATE")
        try:
            result, restock = _refund(conn, order_id, amount_cents, idempotency_key, actor)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    if restock:
        from shop import api

        for sku, qty in restock:
            api.INVENTORY.release(sku, qty)
    return result


def _refund(conn, order_id, amount_cents, idempotency_key, actor):
    row = conn.execute(
        "SELECT id, order_id, amount_cents, actor FROM refunds WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    if row:
        if (row["order_id"], row["amount_cents"], row["actor"]) != (
            order_id,
            amount_cents,
            actor,
        ):
            raise RefundError("idempotency_key was used for a different refund")
        return _as_result(row), []
    order = conn.execute("SELECT email FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        raise RefundError(f"unknown order: {order_id}")
    staff = isinstance(actor, str) and actor.startswith("staff:") and len(actor) > 6
    if actor != order["email"] and not staff:
        raise RefundError("not allowed to refund this order")
    items = conn.execute(
        "SELECT sku, qty, price_cents FROM items WHERE order_id = ?", (order_id,)
    ).fetchall()
    total = sum(i["qty"] * i["price_cents"] for i in items)
    refunded = conn.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) FROM refunds WHERE order_id = ?",
        (order_id,),
    ).fetchone()[0]
    if refunded + amount_cents > total:
        raise RefundError("refund exceeds the order total")
    cur = conn.execute(
        "INSERT INTO refunds (order_id, amount_cents, idempotency_key, actor)"
        " VALUES (?, ?, ?, ?)",
        (order_id, amount_cents, idempotency_key, actor),
    )
    result = _as_result(
        {"id": cur.lastrowid, "order_id": order_id, "amount_cents": amount_cents}
    )
    restock = [(i["sku"], i["qty"]) for i in items] if refunded + amount_cents == total else []
    return result, restock
