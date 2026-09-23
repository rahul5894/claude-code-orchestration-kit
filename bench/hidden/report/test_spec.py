"""Hidden tests for the report ticket. Run through score.py; BENCH_REPO names the repo."""
import os
import shutil
import sys
import tempfile
import time
import unittest

REPO = os.environ.get("BENCH_REPO")
if REPO:
    sys.path.insert(0, os.path.abspath(REPO))
os.environ.setdefault("SHOP_API_KEY", "bench-key")

try:
    from shop import api, db, report

    IMPORT_ERROR = None
except Exception as exc:  # the untouched base has no shop.report
    IMPORT_ERROR = exc


def pick(rows, keys):
    return [{k: r[k] for k in keys} for r in rows]


class ReportCase(unittest.TestCase):
    def setUp(self):
        if IMPORT_ERROR is not None:
            raise IMPORT_ERROR
        self.dir = tempfile.mkdtemp(prefix="bench-report-")
        self.conn = db.connect(os.path.join(self.dir, "shop.db"))

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def add(self, email, created_at, lines):
        """lines: (sku, qty, price_cents). Returns the order id."""
        cur = self.conn.execute(
            "INSERT INTO orders (customer, email, created_at) VALUES (?, ?, ?)",
            (email.split("@")[0], email, created_at),
        )
        self.conn.executemany(
            "INSERT INTO items (order_id, sku, qty, price_cents) VALUES (?, ?, ?, ?)",
            [(cur.lastrowid, s, q, p) for s, q, p in lines],
        )
        self.conn.commit()
        return cur.lastrowid

    def bulk(self, orders, items_per_order, day="2026-03-15"):
        """orders rows, each with items_per_order items, all on one day."""
        self.conn.executemany(
            "INSERT INTO orders (id, customer, email, created_at) VALUES (?, ?, ?, ?)",
            [
                (n, f"c{n % 2000}", f"c{n % 2000}@example.com", f"{day} {n % 24:02d}:00:00")
                for n in range(1, orders + 1)
            ],
        )
        self.conn.executemany(
            "INSERT INTO items (order_id, sku, qty, price_cents) VALUES (?, ?, ?, ?)",
            [
                (n, f"SKU-{(n + k) % 50:02d}", 1 + k, 100 * (k + 1))
                for n in range(1, orders + 1)
                for k in range(items_per_order)
            ],
        )
        self.conn.commit()

    def sample(self):
        """Hand-computed March 2026 dataset, plus one order either side of it."""
        self.add("ana@example.com", "2026-03-01 00:00:00", [("MUG", 2, 500), ("TEE", 1, 1500)])
        self.add("bo@example.com", "2026-03-10 12:00:00", [("CAP", 3, 700)])
        self.add("ana@example.com", "2026-03-31 23:59:59", [("MUG", 1, 500)])
        self.add("cy@example.com", "2026-03-15 08:00:00", [("TEE", 1, 1500), ("PIN", 6, 100)])
        self.add("dan@example.com", "2026-02-28 23:59:59", [("MUG", 50, 500)])
        self.add("eve@example.com", "2026-04-01 00:00:00", [("CAP", 50, 700)])

    # "start and end ... both inclusive, compared against the order's created_at date"
    def test_end_day_is_inclusive(self):
        self.add("a@example.com", "2026-03-12 23:59:59", [("MUG", 1, 100)])
        rep = report.order_report(self.conn, "2026-03-10", "2026-03-12")
        self.assertEqual(rep["orders"], 1)
        self.assertEqual(rep["revenue_cents"], 100)

    def test_days_outside_range_are_excluded(self):
        self.add("a@example.com", "2026-03-10 00:00:00", [("MUG", 1, 100)])
        self.add("b@example.com", "2026-03-13 00:00:00", [("MUG", 1, 20)])
        self.add("c@example.com", "2026-03-09 23:59:59", [("MUG", 1, 3)])
        rep = report.order_report(self.conn, "2026-03-10", "2026-03-12")
        self.assertEqual(rep["orders"], 1)
        self.assertEqual(rep["revenue_cents"], 100)

    def test_start_equal_to_end_is_one_day(self):
        self.add("a@example.com", "2026-03-12 00:00:00", [("MUG", 1, 100)])
        self.add("b@example.com", "2026-03-12 23:59:59", [("MUG", 1, 20)])
        self.add("c@example.com", "2026-03-13 00:00:00", [("MUG", 1, 3)])
        rep = report.order_report(self.conn, "2026-03-12", "2026-03-12")
        self.assertEqual(rep["orders"], 2)
        self.assertEqual(rep["revenue_cents"], 120)

    def test_empty_range(self):
        self.sample()
        rep = report.order_report(self.conn, "2025-01-01", "2025-12-31")
        self.assertEqual(rep["orders"], 0)
        self.assertEqual(rep["revenue_cents"], 0)
        self.assertEqual(list(rep["customers"]), [])
        self.assertEqual(list(rep["top_skus"]), [])

    # "revenue_cents (sum of qty * price_cents over those orders' items)"
    def test_totals(self):
        self.sample()
        rep = report.order_report(self.conn, "2026-03-01", "2026-03-31")
        self.assertEqual(rep["orders"], 4)
        self.assertEqual(rep["revenue_cents"], 7200)

    # "customers ... sorted by revenue_cents descending, then email ascending"
    def test_customers(self):
        self.sample()
        rep = report.order_report(self.conn, "2026-03-01", "2026-03-31")
        self.assertEqual(
            pick(rep["customers"], ("email", "orders", "revenue_cents")),
            [
                {"email": "ana@example.com", "orders": 2, "revenue_cents": 3000},
                {"email": "bo@example.com", "orders": 1, "revenue_cents": 2100},
                {"email": "cy@example.com", "orders": 1, "revenue_cents": 2100},
            ],
        )

    # "top_skus (at most 5 {sku, qty} by total qty descending, then sku ascending)"
    def test_top_skus_order(self):
        self.sample()
        rep = report.order_report(self.conn, "2026-03-01", "2026-03-31")
        self.assertEqual(
            pick(rep["top_skus"], ("sku", "qty")),
            [
                {"sku": "PIN", "qty": 6},
                {"sku": "CAP", "qty": 3},
                {"sku": "MUG", "qty": 3},
                {"sku": "TEE", "qty": 2},
            ],
        )

    def test_top_skus_capped_at_five(self):
        lines = [("S1", 1), ("S2", 5), ("S3", 5), ("S4", 2), ("S5", 9), ("S6", 3), ("S7", 1)]
        self.add("a@example.com", "2026-03-05 10:00:00", [(s, q, 100) for s, q in lines])
        rep = report.order_report(self.conn, "2026-03-01", "2026-03-31")
        self.assertEqual(
            pick(rep["top_skus"], ("sku", "qty")),
            [
                {"sku": "S5", "qty": 9},
                {"sku": "S2", "qty": 5},
                {"sku": "S3", "qty": 5},
                {"sku": "S6", "qty": 3},
                {"sku": "S4", "qty": 2},
            ],
        )

    # "Invalid dates, or start after end, raise ValueError"
    def test_invalid_dates_raise(self):
        # None is not a date string: TypeError is as defensible a reading as ValueError.
        for bad in ("2026-02-30", "2026/01/01", "", None):
            want = (ValueError, TypeError) if bad is None else ValueError
            with self.subTest(start=bad):
                with self.assertRaises(want):
                    report.order_report(self.conn, bad, "2026-03-31")
            with self.subTest(end=bad):
                with self.assertRaises(want):
                    report.order_report(self.conn, "2026-01-01", bad)

    def test_start_after_end_raises(self):
        with self.assertRaises(ValueError):
            report.order_report(self.conn, "2026-03-02", "2026-03-01")

    # "api.order_report ... follows the conventions of the existing handlers"
    def test_api_bad_key(self):
        request = {"api_key": "wrong", "start": "2026-03-01", "end": "2026-03-31"}
        self.assertEqual(api.order_report(self.conn, request), {"status": 403})

    def test_api_bad_date(self):
        request = {"api_key": api.API_KEY, "start": "2026-02-30", "end": "2026-03-31"}
        resp = api.order_report(self.conn, request)
        self.assertEqual(resp.get("status"), 400)
        self.assertIsInstance(resp.get("error"), str)

    def test_api_ok(self):
        self.sample()
        expected = report.order_report(self.conn, "2026-03-01", "2026-03-31")
        request = {"api_key": api.API_KEY, "start": "2026-03-01", "end": "2026-03-31"}
        resp = api.order_report(self.conn, request)
        self.assertEqual(resp.get("status"), 200)
        rest = {k: v for k, v in resp.items() if k != "status"}
        # the report under any one key, or merged into the response
        self.assertTrue(rest == expected or expected in rest.values(), resp)

    # "tens of thousands of orders, so the report must stay fast"
    def test_query_count(self):
        self.bulk(200, 2)
        statements = []
        self.conn.set_trace_callback(statements.append)
        try:
            rep = report.order_report(self.conn, "2026-03-01", "2026-03-31")
        finally:
            self.conn.set_trace_callback(None)
        self.assertEqual(rep["orders"], 200)
        self.assertLessEqual(len(statements), 5, statements[:10])

    def test_speed(self):
        self.bulk(20000, 3)
        began = time.perf_counter()
        rep = report.order_report(self.conn, "2026-03-01", "2026-03-31")
        elapsed = time.perf_counter() - began
        self.assertEqual(rep["orders"], 20000)
        self.assertLess(elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()
