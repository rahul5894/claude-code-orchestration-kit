import datetime
import unittest

from billing import customers, db, invoices, money, subscriptions


class SmokeTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()

    def test_customer_subscription_invoice(self):
        cid = customers.create_customer(self.conn, "ann@example.com", "Ann", "GB")
        sid = subscriptions.subscribe(self.conn, cid, "team", datetime.date(2025, 3, 1))
        sub = subscriptions.get_subscription(self.conn, sid)
        self.assertEqual(sub["period_end"], "2025-04-01")
        [first] = customers.open_invoices(self.conn, cid)
        invoice = invoices.get_invoice(self.conn, first["id"])
        self.assertEqual(invoice["subtotal_cents"], 2900)
        self.assertEqual(invoice["tax_cents"], 580)
        self.assertEqual(invoice["number"], "INV-000001")

    def test_format(self):
        self.assertEqual(money.format_cents(1999), "$19.99")


if __name__ == "__main__":
    unittest.main()
