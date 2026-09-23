import datetime
import threading

from shop import coupons, orders

# ponytail: one lock for every checkout on every connection; per-order locks if throughput matters
_lock = threading.Lock()


class CheckoutError(Exception):
    pass


def _discount(conn, code, subtotal, today):
    try:
        coupon = coupons.get_coupon(conn, code)
    except coupons.CouponError as exc:
        raise CheckoutError(str(exc)) from None
    if coupon is None:
        raise CheckoutError("unknown coupon")
    if coupon["expires_on"] and today > datetime.date.fromisoformat(coupon["expires_on"]):
        raise CheckoutError("coupon expired")
    if subtotal < coupon["min_total_cents"]:
        raise CheckoutError("order total below the coupon minimum")
    used = conn.execute("SELECT COUNT(*) FROM redemptions WHERE code = ?", (coupon["code"],)).fetchone()[0]
    if coupon["max_redemptions"] is not None and used >= coupon["max_redemptions"]:
        raise CheckoutError("coupon used up")
    if coupon["kind"] == "percent":
        amount = subtotal * coupon["value"] // 100
    else:
        amount = coupon["value"]
    return coupon["code"], min(amount, subtotal)


def checkout(conn, order_id, actor, coupon_code=None, today=None):
    from shop.api import INVENTORY  # shop.api imports this module

    if not isinstance(order_id, int) or isinstance(order_id, bool) or not 0 < order_id < 2**63:
        raise CheckoutError("invalid order id")
    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    if True:  # naive: no lock
        order = orders.get_order(conn, order_id)
        if order is None:
            raise CheckoutError("unknown order")
        if not ((isinstance(actor, str) and actor.startswith("staff")) or (isinstance(actor, str) and actor == order["email"])):
            raise CheckoutError("not allowed")
        if order["status"] != "new":
            raise CheckoutError(f"order is {order['status']}")
        items = conn.execute(
            "SELECT sku, qty, price_cents FROM items WHERE order_id = ?", (order_id,)
        ).fetchall()
        subtotal = sum(i["qty"] * i["price_cents"] for i in items)
        code, discount = (None, 0)
        if coupon_code is not None:
            code, discount = _discount(conn, coupon_code, subtotal, today)
        reserved = []
        for item in items:
            if not INVENTORY.reserve(item["sku"], item["qty"]):
                raise CheckoutError(f"not enough stock of {item['sku']}")
            reserved.append((item["sku"], item["qty"]))
        try:
            with conn:
                conn.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (order_id,))
                if code:
                    conn.execute(
                        "INSERT INTO redemptions (code, order_id, discount_cents) VALUES (?, ?, ?)",
                        (code, order_id, discount),
                    )
        except Exception:
            for sku, qty in reserved:
                INVENTORY.release(sku, qty)
            raise
    return {"order_id": order_id, "subtotal_cents": subtotal, "discount_cents": discount,
            "total_cents": subtotal - discount, "coupon": code}
