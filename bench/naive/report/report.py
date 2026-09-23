def order_report(conn, start, end):
    if start > end:
        raise ValueError("start is after end")
    orders = conn.execute(
        "SELECT id, email FROM orders WHERE created_at >= ? AND created_at < ?",
        (start, end),
    ).fetchall()
    revenue = 0
    customers = {}
    skus = {}
    for order in orders:
        items = conn.execute(
            "SELECT sku, qty, price_cents FROM items WHERE order_id = ?", (order["id"],)
        ).fetchall()
        total = sum(i["qty"] * i["price_cents"] for i in items)
        revenue += total
        c = customers.setdefault(
            order["email"], {"email": order["email"], "orders": 0, "revenue_cents": 0}
        )
        c["orders"] += 1
        c["revenue_cents"] += total
        for i in items:
            skus[i["sku"]] = skus.get(i["sku"], 0) + i["qty"]
    return {
        "orders": len(orders),
        "revenue_cents": revenue,
        "customers": sorted(
            customers.values(), key=lambda c: (-c["revenue_cents"], c["email"])
        ),
        "top_skus": [
            {"sku": s, "qty": q}
            for s, q in sorted(skus.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        ],
    }
