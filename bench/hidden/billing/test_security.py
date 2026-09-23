"""Who may do what, and no internal detail in a response."""
from billing_base import KEY, Base, D, api


def leaks(response):
    text = repr(response)
    return any(s in text for s in ("Traceback", "File \"", "Error:", "sqlite3"))


class Security(Base):
    def setUp(self):
        super().setUp()
        self.ann = self.customer("ann@example.com")
        self.bob = self.customer("bob@example.com")
        self.sid = self.subscribe(self.ann, "team", D(2025, 3, 1))
        self.inv = self.conn.execute("SELECT id FROM invoices WHERE customer_id = ?", (self.ann,)).fetchone()[0]

    def test_invoice_of_another_customer(self):
        r = api.get_invoice(self.conn, {"api_key": KEY, "actor": "bob@example.com", "invoice_id": self.inv})
        self.assertIn(r["status"], (403, 404))
        self.assertNotIn("invoice", r)

    def test_invoice_own_and_staff(self):
        for actor in ("ann@example.com", "staff:x"):
            with self.subTest(actor=actor):
                r = api.get_invoice(self.conn, {"api_key": KEY, "actor": actor, "invoice_id": self.inv})
                self.assertEqual(r["status"], 200)

    def test_bad_invoice_id_is_400_without_details(self):
        for bad in ("abc", None, [1]):
            with self.subTest(bad=bad):
                r = api.get_invoice(self.conn, {"api_key": KEY, "actor": "staff:x", "invoice_id": bad})
                self.assertEqual(r["status"], 400)
                self.assertFalse(leaks(r), r)

    def test_create_customer_bad_email_no_details(self):
        r = api.create_customer(self.conn, {"api_key": KEY, "actor": "staff:x", "email": None,
                                            "name": "X", "region": "GB"})
        self.assertEqual(r["status"], 400)
        self.assertFalse(leaks(r), r)

    def test_change_plan_by_another_customer(self):
        before = self.state()
        r = api.change_plan(self.conn, {"api_key": KEY, "actor": "bob@example.com",
                                         "subscription_id": self.sid, "plan": "business", "on": "2025-03-10"})
        self.assertEqual(r["status"], 403)
        self.assertEqual(self.state(), before)

    def test_staff_prefix_is_exact(self):
        for actor in ("Staff:x", "staff", "xstaff:y", None):
            with self.subTest(actor=actor):
                r = api.change_plan(self.conn, {"api_key": KEY, "actor": actor, "subscription_id": self.sid,
                                                 "plan": "business", "on": "2025-03-10"})
                self.assertEqual(r["status"], 403)

    def test_statement_of_another_customer(self):
        r = api.statement(self.conn, {"api_key": KEY, "actor": "bob@example.com", "customer_id": self.ann})
        self.assertEqual(r["status"], 403)
        self.assertNotIn("invoices", r)

    def test_api_key_required_everywhere(self):
        calls = [
            (api.change_plan, {"actor": "staff:x", "subscription_id": self.sid, "plan": "business", "on": "2025-03-10"}),
            (api.statement, {"actor": "staff:x", "customer_id": self.ann}),
            (api.get_invoice, {"actor": "staff:x", "invoice_id": self.inv}),
        ]
        for fn, req in calls:
            for key in (None, "", "bench-key ", "BENCH-KEY", 1):
                with self.subTest(fn=fn.__name__, key=key):
                    self.assertEqual(fn(self.conn, {**req, "api_key": key})["status"], 403)
