class RefundError(Exception):
    pass


def refund(conn, order_id, amount_cents, idempotency_key, actor):
    if not isinstance(amount_cents, int) or amount_cents <= 0:
        raise RefundError("amount_cents must be a positive integer")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS refunds (id INTEGER PRIMARY KEY, order_id INTEGER,"
        " amount_cents INTEGER, idempotency_key TEXT, actor TEXT)"
    )
    row = conn.execute(
        "SELECT id, order_id, amount_cents FROM refunds WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    if row:
        return {
            "refund_id": row["id"],
            "order_id": row["order_id"],
            "amount_cents": row["amount_cents"],
            "status": "refunded",
        }
    order = conn.execute("SELECT email FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        raise RefundError("unknown order")
    if actor != order["email"] and not actor.startswith("staff:"):
        raise RefundError("not allowed")
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
    conn.commit()
    if refunded + amount_cents == total:
        from shop import api

        for i in items:
            api.INVENTORY.release(i["sku"], i["qty"])
    return {
        "refund_id": cur.lastrowid,
        "order_id": order_id,
        "amount_cents": amount_cents,
        "status": "refunded",
    }
