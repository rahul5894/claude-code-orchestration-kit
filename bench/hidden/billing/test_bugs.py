"""The bugs seeded in the legacy modules. Each contradicts the function's own docstring, and the
ticket asks the arm to fix every real bug it finds there. One test per bug."""
from billing_base import Base, D, customers, dates, invoices, money, proration, run_together, tax


class Bugs(Base):
    def test_to_cents_is_exact(self):
        self.assertEqual(money.to_cents("19.99"), 1999)
        self.assertEqual(money.to_cents("0.29"), 29)
        self.assertEqual(money.to_cents("-3.10"), -310)
        self.assertEqual(money.to_cents(7), 700)

    def test_to_cents_rejects_non_amounts(self):
        for bad in ("1.005", "nan", "inf", "", "1e3", 1.5, True, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                money.to_cents(bad)

    def test_format_negative(self):
        self.assertEqual(money.format_cents(-150), "-$1.50")
        self.assertEqual(money.format_cents(-5), "-$0.05")
        self.assertEqual(money.format_cents(123456789), "$1,234,567.89")

    def test_add_months_clamps(self):
        self.assertEqual(dates.add_months(D(2025, 1, 31), 1), D(2025, 2, 28))
        self.assertEqual(dates.add_months(D(2024, 1, 31), 1), D(2024, 2, 29))
        self.assertEqual(dates.add_months(D(2025, 3, 31), -1), D(2025, 2, 28))
        self.assertEqual(dates.add_months(D(2025, 12, 15), 1), D(2026, 1, 15))

    def test_prorate_uses_real_period_length(self):
        self.assertEqual(proration.prorate(2800, D(2025, 2, 1), D(2025, 3, 1), D(2025, 2, 15)), 1400)
        self.assertEqual(proration.prorate(3100, D(2025, 3, 1), D(2025, 4, 1), D(2025, 3, 1)), 3100)

    def test_prorate_outside_period(self):
        for day in (D(2025, 2, 28), D(2025, 4, 1), D(2025, 4, 2)):
            with self.subTest(day=day), self.assertRaises(ValueError):
                proration.prorate(3100, D(2025, 3, 1), D(2025, 4, 1), day)

    def test_tax_rounds_half_up(self):
        self.assertEqual(tax.tax_for("US-CA", 200), 15)   # 14.5
        self.assertEqual(tax.tax_for("DE", 150), 29)      # 28.5
        self.assertEqual(tax.tax_for("IN", 25), 5)        # 4.5
        self.assertEqual(tax.tax_for("US-NY", 1200), 107)  # 106.5

    def test_tax_unknown_region(self):
        with self.assertRaises(ValueError):
            tax.tax_for("FR", 1000)

    def test_email_case_insensitive(self):
        self.assertEqual(customers.normalize_email("  Ann@Example.COM "), "ann@example.com")
        customers.create_customer(self.conn, "Ann@Example.com", "Ann", "GB")
        with self.assertRaises(customers.CustomerError):
            customers.create_customer(self.conn, "ann@example.com", "Ann 2", "GB")

    def test_open_invoices_no_shared_default(self):
        a = customers.create_customer(self.conn, "a@example.com", "A", "GB")
        b = customers.create_customer(self.conn, "b@example.com", "B", "GB")
        invoices.issue_invoice(self.conn, a, None, [("x", 100)], D(2025, 1, 1))
        invoices.issue_invoice(self.conn, b, None, [("y", 200)], D(2025, 1, 1))
        self.assertEqual(len(customers.open_invoices(self.conn, a)), 1)
        self.assertEqual([i["total_cents"] for i in customers.open_invoices(self.conn, b)], [240])

    def test_issue_invoice_all_or_nothing(self):
        cid = customers.create_customer(self.conn, "a@example.com", "A", "GB")
        before = self.state()
        with self.assertRaises(Exception):  # any error type; the point is nothing stays
            invoices.issue_invoice(self.conn, cid, None, [("ok", 100), (None, 50)], D(2025, 1, 1))
        self.assertEqual(self.state(), before)

    def test_invoice_numbers_unique_under_threads(self):
        cid = customers.create_customer(self.conn, "a@example.com", "A", "GB")
        for _ in range(3):
            conns = [self.connect() for _ in range(8)]
            out = run_together([lambda c=c: invoices.issue_invoice(c, cid, None, [("x", 100)], D(2025, 1, 1))
                                for c in conns])
            self.assertEqual([e for _, e in out if e], [])
        numbers = [r[0] for r in self.conn.execute("SELECT number FROM invoices")]
        self.assertEqual(len(numbers), 24)
        self.assertEqual(len(set(numbers)), 24)

    def test_parse_date_none(self):
        with self.assertRaises(ValueError):
            dates.parse_date(None)
