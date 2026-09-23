import unittest

from shop import db, orders, validate
from shop.inventory import Inventory


class SmokeTest(unittest.TestCase):
    def test_email_ok(self):
        self.assertTrue(validate.email_ok("ana@example.com"))
        self.assertFalse(validate.email_ok("ana@example"))
        self.assertFalse(validate.email_ok(None))

    def test_stock_of(self):
        inv = Inventory({"MUG-0001": 5})
        inv.restock("MUG-0001", 2)
        self.assertEqual(inv.stock_of("MUG-0001"), 7)
        self.assertEqual(inv.stock_of("CAP-0001"), 0)

    def test_sort_orders(self):
        conn = db.connect()
        conn.executemany(
            "INSERT INTO orders (customer, email) VALUES (?, ?)",
            [("bo", "bo@example.com"), ("al", "al@example.com")],
        )
        names = [r["customer"] for r in orders.sort_orders(conn, "customer")]
        self.assertEqual(names, ["al", "bo"])
        with self.assertRaises(ValueError):
            orders.sort_orders(conn, "email")


if __name__ == "__main__":
    unittest.main()
