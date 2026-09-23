"""Robustness the ticket implies: threads, bad input, edge sizes. Never a crash."""
import threading
import unittest

from checkout_base import OWNER, STAFF, TODAY, Base, api, checkout, coupons, db, orders


def run_threads(fn, args_list):
    """Start every call at once; return the results (the exception object on failure)."""
    results = [None] * len(args_list)
    gate = threading.Barrier(len(args_list))

    def work(i, args):
        gate.wait()
        try:
            results[i] = fn(*args)
        except Exception as exc:  # noqa: BLE001 - the test inspects what came back
            results[i] = exc

    # daemon: a thread stuck in a deadlocked checkout must not keep the test process alive
    threads = [threading.Thread(target=work, args=(i, a), daemon=True) for i, a in enumerate(args_list)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    return results


class Threads(Base):
    def test_max_redemptions_under_threads(self):
        coupons.create_coupon(self.conn, STAFF, "THREE", "fixed", 100, max_redemptions=3)
        ids = [self.order([("TEE-0001", 1)]) for _ in range(12)]
        res = run_threads(lambda oid: checkout.checkout(self.conn, oid, OWNER, coupon_code="THREE", today=TODAY),
                          [(oid,) for oid in ids])
        ok = [r for r in res if isinstance(r, dict)]
        refused = [r for r in res if isinstance(r, checkout.CheckoutError)]
        self.assertEqual((len(ok), len(refused)), (3, 9), res)
        self.assertEqual(coupons.redemption_count(self.conn, "THREE"), 3)
        self.assertEqual(sum(self.status(oid) == "paid" for oid in ids), 3)

    def test_same_order_on_many_threads(self):
        oid = self.order([("CAP-0001", 2)])
        before = self.stock("CAP-0001")
        res = run_threads(lambda: checkout.checkout(self.conn, oid, OWNER, today=TODAY), [()] * 8)
        self.assertEqual(sum(isinstance(r, dict) for r in res), 1, res)
        self.assertTrue(all(isinstance(r, (dict, checkout.CheckoutError)) for r in res), res)
        self.assertEqual(self.stock("CAP-0001"), before - 2)


class BadInput(Base):
    def test_checkout_handler_never_raises(self):
        oid = self.order()
        for req in ({}, {"order_id": None, "actor": OWNER}, {"order_id": "abc", "actor": OWNER},
                    {"order_id": oid}, {"order_id": oid, "actor": None}, {"order_id": oid, "actor": 5},
                    {"order_id": [oid], "actor": OWNER}, {"order_id": oid, "actor": OWNER, "coupon": 7},
                    {"order_id": 10**30, "actor": OWNER}):
            with self.subTest(req=req):
                r = api.checkout_order(self.conn, req)
                self.assertTrue(400 <= r["status"] < 500, r)
        self.assertEqual(self.status(oid), "new")

    def test_create_coupon_handler_never_raises(self):
        base = {"api_key": "bench-key", "actor": STAFF, "code": "OK-1", "kind": "fixed", "value": 100}
        # a numeric string ("100") is left out: converting it is a defensible reading
        for change in ({"value": None}, {"value": [100]}, {"code": None}, {"kind": None},
                       {"max_redemptions": 0}, {"min_total_cents": -1},
                       {"expires_on": "not-a-date"}, {"actor": None}):
            with self.subTest(change=change):
                r = api.create_coupon(self.conn, {**base, **change})
                self.assertTrue(400 <= r["status"] < 500, r)

    def test_checkout_unknown_order(self):
        with self.assertRaises(checkout.CheckoutError):
            checkout.checkout(self.conn, 999999, STAFF, today=TODAY)

    def test_checkout_bad_actor_type(self):
        oid = self.order()
        for actor in (None, 5, ["staff:1"]):
            with self.subTest(actor=actor), self.assertRaises(checkout.CheckoutError):
                checkout.checkout(self.conn, oid, actor, today=TODAY)


class ReportEdges(Base):
    def test_empty_list(self):
        self.assertEqual(orders.summaries(self.conn, []), {})

    def test_order_without_items(self):
        oid = self.conn.execute("INSERT INTO orders (customer, email) VALUES ('Bo', 'bo@example.com')").lastrowid
        self.conn.commit()
        self.assertEqual(orders.summaries(self.conn, [oid]),
                         {oid: {"status": "new", "item_count": 0, "total_cents": 0}})

    def test_ten_thousand_ids(self):
        conn = db.connect()
        self.conns.append(conn)
        real = self.order(conn=conn)
        got = orders.summaries(conn, [real] + list(range(10**6, 10**6 + 9999)))
        self.assertEqual(list(got), [real])


if __name__ == "__main__":
    unittest.main()
