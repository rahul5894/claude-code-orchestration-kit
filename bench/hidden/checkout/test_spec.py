"""Spec: what the checkout ticket states outright."""
import datetime
import unittest

from checkout_base import OWNER, STAFF, TODAY, Base, api, checkout, coupons, db, orders


def co(conn, order_id, actor=OWNER, code=None, today=TODAY):
    return checkout.checkout(conn, order_id, actor, coupon_code=code, today=today)


class Coupons(Base):
    def test_create_returns_upper_code(self):
        self.assertEqual(coupons.create_coupon(self.conn, STAFF, "save10", "percent", 10), "SAVE10")

    def test_duplicate_code_case_insensitive(self):
        coupons.create_coupon(self.conn, STAFF, "SAVE10", "percent", 10)
        with self.assertRaises(coupons.CouponError):
            coupons.create_coupon(self.conn, STAFF, "save10", "fixed", 100)

    def test_invalid_kind_or_value(self):
        for kind, value in (("percent", 0), ("percent", 101), ("fixed", 0), ("bogus", 5)):
            with self.subTest(kind=kind, value=value), self.assertRaises(coupons.CouponError):
                coupons.create_coupon(self.conn, STAFF, "C-" + kind[:3].upper() + str(value), kind, value)

    def test_invalid_code(self):
        for code in ("ab", "A" * 21, "SAVE 10", "SAVE_10"):
            with self.subTest(code=code), self.assertRaises(coupons.CouponError):
                coupons.create_coupon(self.conn, STAFF, code, "percent", 10)

    def test_non_staff_cannot_create(self):
        with self.assertRaises(coupons.CouponError):
            coupons.create_coupon(self.conn, OWNER, "SAVE10", "percent", 10)

    def test_redemption_count(self):
        coupons.create_coupon(self.conn, STAFF, "SAVE10", "percent", 10)
        self.assertEqual(coupons.redemption_count(self.conn, "save10"), 0)
        with self.assertRaises(coupons.CouponError):
            coupons.redemption_count(self.conn, "NOPE-1")


class Checkout(Base):
    def test_plain_checkout(self):
        oid = self.order()  # 2 x MUG-0001 at 1299
        before = self.stock("MUG-0001")
        r = co(self.conn, oid)
        self.assertEqual((r["order_id"], r["subtotal_cents"], r["discount_cents"], r["total_cents"], r["coupon"]),
                         (oid, 2598, 0, 2598, None))
        self.assertEqual(self.status(oid), "paid")
        self.assertEqual(self.stock("MUG-0001"), before - 2)

    def test_percent_rounds_down(self):
        coupons.create_coupon(self.conn, STAFF, "SAVE10", "percent", 10)
        r = co(self.conn, self.order(), code="save10")  # 10% of 2598 = 259.8
        self.assertEqual((r["discount_cents"], r["total_cents"], r["coupon"]), (259, 2339, "SAVE10"))

    def test_fixed(self):
        coupons.create_coupon(self.conn, STAFF, "FIVE", "fixed", 500)
        r = co(self.conn, self.order(), code="FIVE")
        self.assertEqual((r["discount_cents"], r["total_cents"]), (500, 2098))

    def test_total_never_below_zero(self):
        coupons.create_coupon(self.conn, STAFF, "BIG", "fixed", 100000)
        self.assertEqual(co(self.conn, self.order(), code="BIG")["total_cents"], 0)

    def test_minimum_not_met(self):
        coupons.create_coupon(self.conn, STAFF, "MIN", "fixed", 100, min_total_cents=2599)
        oid = self.order()
        before = self.stock("MUG-0001")
        with self.assertRaises(checkout.CheckoutError):
            co(self.conn, oid, code="MIN")
        self.assertEqual((self.status(oid), self.stock("MUG-0001")), ("new", before))
        self.assertEqual(coupons.redemption_count(self.conn, "MIN"), 0)

    def test_minimum_met_exactly(self):
        coupons.create_coupon(self.conn, STAFF, "MIN", "fixed", 100, min_total_cents=2598)
        self.assertEqual(co(self.conn, self.order(), code="MIN")["total_cents"], 2498)

    def test_expiry_is_inclusive(self):
        coupons.create_coupon(self.conn, STAFF, "LAST", "fixed", 100, expires_on=TODAY)
        self.assertEqual(co(self.conn, self.order(), code="LAST", today=TODAY)["discount_cents"], 100)
        with self.assertRaises(checkout.CheckoutError):
            co(self.conn, self.order(), code="LAST", today=TODAY + datetime.timedelta(days=1))

    def test_max_redemptions(self):
        coupons.create_coupon(self.conn, STAFF, "ONCE", "fixed", 100, max_redemptions=1)
        co(self.conn, self.order(), code="ONCE")
        oid = self.order()
        with self.assertRaises(checkout.CheckoutError):
            co(self.conn, oid, code="ONCE")
        self.assertEqual(self.status(oid), "new")
        self.assertEqual(coupons.redemption_count(self.conn, "ONCE"), 1)

    def test_unknown_coupon(self):
        oid = self.order()
        with self.assertRaises(checkout.CheckoutError):
            co(self.conn, oid, code="NOPE-1")
        self.assertEqual(self.status(oid), "new")

    def test_staff_may_check_out(self):
        oid = self.order()
        co(self.conn, oid, actor=STAFF)
        self.assertEqual(self.status(oid), "paid")

    def test_only_new_orders(self):
        oid = self.order()
        co(self.conn, oid)
        after_first = self.stock("MUG-0001")
        with self.assertRaises(checkout.CheckoutError):
            co(self.conn, oid)
        self.assertEqual(self.stock("MUG-0001"), after_first)

    def test_stock_all_or_nothing(self):
        tee, mug2 = self.stock("TEE-0001"), self.stock("MUG-0002")
        oid = self.order([("TEE-0001", 1), ("MUG-0002", mug2 + 1)])
        with self.assertRaises(checkout.CheckoutError):
            co(self.conn, oid)
        self.assertEqual((self.stock("TEE-0001"), self.stock("MUG-0002"), self.status(oid)), (tee, mug2, "new"))

    def test_failed_checkout_does_not_use_the_coupon(self):
        coupons.create_coupon(self.conn, STAFF, "ONCE", "fixed", 100, max_redemptions=1)
        bad = self.order([("MUG-0002", self.stock("MUG-0002") + 1)])
        with self.assertRaises(checkout.CheckoutError):
            co(self.conn, bad, code="ONCE")
        self.assertEqual(coupons.redemption_count(self.conn, "ONCE"), 0)
        co(self.conn, self.order(), code="ONCE")

    def test_redemptions_live_in_the_database(self):
        # two databases, same code: using it up in one must not use it up in the other
        other = self.connect("other.db")
        for conn in (self.conn, other):
            coupons.create_coupon(conn, STAFF, "ONCE", "fixed", 100, max_redemptions=1)
        co(self.conn, self.order(), code="ONCE")
        co(other, self.order(conn=other), code="ONCE")
        reopened = self.connect("shop.db")
        self.assertEqual(coupons.redemption_count(reopened, "ONCE"), 1)


class Api(Base):
    def test_checkout_order(self):
        oid = self.order()
        r = api.checkout_order(self.conn, {"order_id": oid, "actor": OWNER})
        self.assertIn(r["status"], (200, 201))
        self.assertEqual(self.status(oid), "paid")

    def test_checkout_order_refused(self):
        oid = self.order()
        r = api.checkout_order(self.conn, {"order_id": oid, "actor": OWNER, "coupon": "NOPE-1"})
        self.assertTrue(400 <= r["status"] < 500, r)
        self.assertEqual(self.status(oid), "new")

    def test_create_coupon(self):
        r = api.create_coupon(self.conn, {"api_key": "bench-key", "actor": STAFF, "code": "api-1",
                                          "kind": "fixed", "value": 100})
        self.assertIn(r["status"], (200, 201))
        self.assertEqual(coupons.redemption_count(self.conn, "API-1"), 0)

    def test_create_coupon_iso_expiry(self):
        r = api.create_coupon(self.conn, {"api_key": "bench-key", "actor": STAFF, "code": "OLD",
                                          "kind": "fixed", "value": 100, "expires_on": "2099-03-09"})
        self.assertIn(r["status"], (200, 201))
        with self.assertRaises(checkout.CheckoutError):
            co(self.conn, self.order(), code="OLD", today=TODAY)


class Report(Base):
    def test_summaries(self):
        a = self.order([("MUG-0001", 2), ("CAP-0001", 1)])
        b = self.order([("TEE-0001", 3)])
        co(self.conn, b)
        got = orders.summaries(self.conn, [a, b, 999999])
        self.assertEqual(got, {
            a: {"status": "new", "item_count": 3, "total_cents": 2 * 1299 + 1800},
            b: {"status": "paid", "item_count": 3, "total_cents": 3 * 2200},
        })

    def test_no_query_per_order(self):
        conn = db.connect()  # in memory: 1000 file commits would only slow the test
        self.conns.append(conn)
        ids = [self.order(conn=conn) for _ in range(1000)]
        selects = []
        conn.set_trace_callback(lambda sql: selects.append(sql) if sql.lstrip().upper().startswith(("SELECT", "WITH")) else None)
        try:
            got = orders.summaries(conn, ids)
        finally:
            conn.set_trace_callback(None)
        self.assertEqual(len(got), 1000)
        self.assertLessEqual(len(selects), 25, f"{len(selects)} SELECTs for 1000 orders")  # chunking is fine; one per order is not


if __name__ == "__main__":
    unittest.main()
