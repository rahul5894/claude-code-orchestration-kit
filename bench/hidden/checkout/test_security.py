"""Security: who may do what, and hostile input. Written from the ticket's rules only."""
import unittest

from checkout_base import OWNER, STAFF, TODAY, Base, api, checkout, coupons


class WhoMayCheckOut(Base):
    def assert_refused(self, actor):
        oid = self.order()
        before = self.stock("MUG-0001")
        with self.assertRaises(checkout.CheckoutError):
            checkout.checkout(self.conn, oid, actor, today=TODAY)
        self.assertEqual((self.status(oid), self.stock("MUG-0001")), ("new", before))

    def test_other_customer(self):
        self.assert_refused("eve@example.com")

    def test_lookalike_of_the_owner(self):
        for actor in ("ana@example.com.evil.io", "xana@example.com", "ana@example"):
            with self.subTest(actor=actor):
                self.assert_refused(actor)

    def test_not_quite_staff(self):
        for actor in ("staff", "staff-7", "mystaff:7", ""):
            with self.subTest(actor=actor):
                self.assert_refused(actor)

    def test_handler_refuses_other_customer(self):
        oid = self.order()
        r = api.checkout_order(self.conn, {"order_id": oid, "actor": "eve@example.com"})
        self.assertTrue(400 <= r["status"] < 500, r)
        self.assertEqual(self.status(oid), "new")


class WhoMayCreateCoupons(Base):
    def test_not_quite_staff(self):
        for actor in ("staff", "customer:staff:1", OWNER, None):
            with self.subTest(actor=actor), self.assertRaises(coupons.CouponError):
                coupons.create_coupon(self.conn, actor, "SAVE10", "percent", 10)

    def test_handler_needs_the_api_key(self):
        req = {"actor": STAFF, "code": "KEYLESS", "kind": "fixed", "value": 100}
        for key in (None, "wrong", ""):
            with self.subTest(key=key):
                r = api.create_coupon(self.conn, {**req, "api_key": key} if key is not None else req)
                self.assertEqual(r["status"], 403, r)
        with self.assertRaises(coupons.CouponError):
            coupons.redemption_count(self.conn, "KEYLESS")

    def test_handler_needs_staff(self):
        r = api.create_coupon(self.conn, {"api_key": "bench-key", "actor": OWNER, "code": "NOSTAFF",
                                          "kind": "fixed", "value": 100})
        self.assertTrue(400 <= r["status"] < 500, r)


class HostileCodes(Base):
    def test_injection_at_checkout(self):
        coupons.create_coupon(self.conn, STAFF, "REAL-1", "percent", 50)
        for code in ("x' OR '1'='1", "REAL-1' --", "%", "REAL-_"):
            with self.subTest(code=code):
                oid = self.order()
                with self.assertRaises(checkout.CheckoutError):
                    checkout.checkout(self.conn, oid, OWNER, coupon_code=code, today=TODAY)
                self.assertEqual(self.status(oid), "new")

    def test_injection_at_create(self):
        for code in ("x' OR '1'='1", "A'); DROP TABLE orders; --"):
            with self.subTest(code=code), self.assertRaises(coupons.CouponError):
                coupons.create_coupon(self.conn, STAFF, code, "percent", 10)
        self.assertIsNotNone(self.conn.execute("SELECT count(*) FROM orders").fetchone())


if __name__ == "__main__":
    unittest.main()
