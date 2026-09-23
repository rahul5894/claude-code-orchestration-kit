"""Robustness tests for the refunds ticket, from the ticket text only. Run through score.py.

Ticket: RefundError "for every refund that is not allowed"; the handler "follows the
conventions of the existing handlers" (a 4xx dict, never an exception). A value marked
`judgement` is refused here although the ticket does not clearly say it must be.
"""
import os
import unittest
import uuid

from test_spec import OWNER, RefundCase

KEY = "robust-key"


class RobustTests(RefundCase):
    def assert_refused(self, **kwargs):
        """refund() with one bad argument raises RefundError and writes no row."""
        args = {"order_id": self.order_id, "amount_cents": 10,
                "idempotency_key": uuid.uuid4().hex, "actor": OWNER}
        args.update(kwargs)
        before = self.refund_rows()
        with self.assertRaises(self.refunds.RefundError):
            self.refunds.refund(self.conn, **args)
        self.assertEqual(self.refund_rows(), before, "a refused refund wrote a row")

    def setUp(self):
        super().setUp()
        from shop import refunds

        self.refunds = refunds
        self.refund(1)  # the refunds table exists, so "no row written" is measurable

    def test_bad_order_id(self):
        for value in (
            str(self.order_id),  # judgement: the real id as text
            None,
            float(self.order_id),  # judgement: the real id as a float
            True,  # judgement: bool is an int subclass and True == the first order's id
            2**63,
            -1,
        ):
            with self.subTest(order_id=value):
                self.assert_refused(order_id=value)

    def test_bad_amount(self):
        for value in ("10", None, 2**63):
            with self.subTest(amount_cents=value):
                self.assert_refused(amount_cents=value)

    def test_bad_idempotency_key(self):
        # judgement (None, "", 7): the ticket says requests carry a key, not that a keyless
        # one is refused. judgement ("\ud800"): an unstorable key must be refused, not crash. No length
        # limit is tested: the ticket states none, so a long key is a defensible accept.
        for value in (None, "", 7, "\ud800"):
            with self.subTest(idempotency_key=repr(value)[:20]):
                self.assert_refused(idempotency_key=value)

    def test_bad_actor(self):
        for value in (None, "", 42, "staff:"):  # judgement: "staff:" with an empty id
            with self.subTest(actor=value):
                self.assert_refused(actor=value)

    def test_stranger_reusing_owner_key_is_refused(self):
        first = self.refund(10, KEY)
        before = self.refund_rows()
        with self.assertRaises(self.refunds.RefundError):
            self.refund(10, KEY, actor="eve@example.com")
        self.assertEqual(self.refund_rows(), before)
        again = self.refund(10, KEY)
        self.assertEqual((again["refund_id"], again["amount_cents"]), (first["refund_id"], 10))

    def request(self, **overrides):
        request = {"api_key": os.environ["SHOP_API_KEY"], "order_id": self.order_id,
                   "amount_cents": 10, "idempotency_key": KEY, "actor": OWNER}
        request.update(overrides)
        return request

    def assert_4xx(self, request):
        try:
            result = self.call_handler(request)
        except Exception as exc:
            self.fail(f"handler raised {exc!r}")
        self.assertIsInstance(result, dict)
        self.assertTrue(400 <= result.get("status", 0) < 500, result)

    def test_api_bad_values_return_4xx(self):
        bad = {
            "order_id": ("abc", None, float(self.order_id), 2**63, -1),  # float: judgement
            "amount_cents": ("10", None, 2**63),  # "10": judgement (list_orders coerces)
            "idempotency_key": (None, "", 7, "\ud800"),  # judgement; no length rule, the ticket states none
            "actor": (None, "", 42, "staff:"),  # "staff:": judgement
        }
        for field, values in bad.items():
            for value in values:
                with self.subTest(field=field, value=repr(value)[:20]):
                    self.assert_4xx(self.request(**{field: value}))

    def test_api_missing_fields_return_4xx(self):
        for field in ("order_id", "amount_cents", "idempotency_key", "actor"):
            with self.subTest(missing=field):
                request = self.request()
                del request[field]
                self.assert_4xx(request)


if __name__ == "__main__":
    unittest.main()
