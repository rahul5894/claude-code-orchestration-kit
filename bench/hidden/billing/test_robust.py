"""What the ticket implies under load, concurrency and hostile input."""
import time

from billing_base import KEY, Base, D, api, db, run_together, subscriptions

GARBAGE = [None, "", "abc", [], {}, True, -1, 0, 10**30, 1.5, float("nan"), "\ud800", "2025-02-30", "1e3"]


def bulk_subscriptions(conn, n, start=D(2025, 3, 1), plan="basic"):
    """n customers with one subscription each, inserted directly (fast setup)."""
    with conn:
        conn.executemany("INSERT INTO customers (email, name, region) VALUES (?, ?, 'GB')",
                         [(f"c{i}@example.com", f"C{i}") for i in range(n)])
        ids = [r[0] for r in conn.execute("SELECT id FROM customers ORDER BY id DESC LIMIT ?", (n,))]
        conn.executemany(
            "INSERT INTO subscriptions (customer_id, plan, started_on, period_start, period_end)"
            " VALUES (?, ?, ?, ?, ?)",
            [(cid, plan, start.isoformat(), start.isoformat(), "2025-04-01") for cid in ids])


class Robust(Base):
    def test_handlers_never_raise(self):
        cid = self.customer()
        sid = self.subscribe(cid)
        good = {
            api.change_plan: {"actor": "staff:x", "subscription_id": sid, "plan": "business", "on": "2025-03-10"},
            api.statement: {"actor": "staff:x", "customer_id": cid, "limit": 2},
            api.get_invoice: {"actor": "staff:x", "invoice_id": 1},
            api.create_customer: {"actor": "staff:x", "email": "z@example.com", "name": "Z", "region": "GB"},
        }
        for fn, req in good.items():
            for field in list(req) + ["cursor"]:
                for value in GARBAGE:
                    with self.subTest(fn=fn.__name__, field=field, value=value):
                        try:
                            r = fn(self.conn, {**req, "api_key": KEY, field: value})
                        except Exception as exc:
                            self.fail(f"raised {exc!r}")
                        self.assertIsInstance(r, dict)
                        self.assertIsInstance(r.get("status"), int)
                        self.assertNotIn("Traceback", repr(r))

    def test_same_upgrade_twice_at_once_is_billed_once(self):
        cid = self.customer()
        for trial in range(15):
            sid = self.subscribe(cid, "team", D(2025, 3, 1))
            before = self.count("invoices")
            c1, c2 = self.connect(), self.connect()
            out = run_together([
                lambda c=c1: subscriptions.change_plan(c, sid, "business", "staff:x", D(2025, 3, 10)),
                lambda c=c2: subscriptions.change_plan(c, sid, "business", "staff:x", D(2025, 3, 10)),
            ])
            with self.subTest(trial=trial):
                ok = [r for r, e in out if e is None]
                errors = [e for _, e in out if e is not None]
                self.assertEqual(len(ok), 1, out)
                self.assertTrue(all(isinstance(e, subscriptions.SubscriptionError) for e in errors), errors)
                self.assertEqual(self.count("invoices"), before + 1)

    def test_concurrent_runs_issue_each_invoice_once(self):
        bulk_subscriptions(self.conn, 40)
        conns = [self.connect() for _ in range(4)]
        out = run_together([lambda c=c: subscriptions.run_billing(c, D(2025, 4, 1)) for c in conns])
        self.assertEqual([e for _, e in out if e], [])
        issued = sorted(i for r, _ in out for i in r)
        self.assertEqual(len(issued), 40)
        self.assertEqual(len(set(issued)), 40)
        self.assertEqual(self.count("invoices"), 40)
        ends = {r[0] for r in self.conn.execute("SELECT period_end FROM subscriptions")}
        self.assertEqual(ends, {"2025-05-01"})

    def _selects(self, n):
        conn = db.connect(self.path.replace(".db", f"-{n}.db"))
        self.addCleanup(conn.close)
        bulk_subscriptions(conn, n)
        seen = []
        conn.set_trace_callback(seen.append)
        subscriptions.run_billing(conn, D(2025, 4, 1))
        conn.set_trace_callback(None)
        return sum(1 for s in seen if s.lstrip().upper().startswith(("SELECT", "WITH")))

    def test_selects_do_not_grow_with_subscriptions(self):
        small, large = self._selects(10), self._selects(120)
        self.assertLessEqual(large, small, f"10 subs: {small} SELECTs, 120 subs: {large}")

    def test_large_run_is_fast(self):
        bulk_subscriptions(self.conn, 3000)
        start = time.perf_counter()
        ids = subscriptions.run_billing(self.conn, D(2025, 4, 1))
        elapsed = time.perf_counter() - start
        self.assertEqual(len(ids), 3000)
        self.assertLess(elapsed, 15, f"{elapsed:.1f} s for 3000 renewals")

    def test_credit_shared_by_two_subscriptions_is_used_once(self):
        cid = self.customer()
        self.subscribe(cid, "basic", D(2025, 3, 1))
        self.subscribe(cid, "basic", D(2025, 3, 1))
        with self.conn:
            self.conn.execute("UPDATE customers SET credit_cents = 1000 WHERE id = ?", (cid,))
        ids = subscriptions.run_billing(self.conn, D(2025, 4, 1))
        applied = -sum(amount for i in ids for desc, amount in self.lines(i) if desc == "Credit applied")
        self.assertEqual(applied, 1000)
        self.assertEqual(self.credit(cid), 0)
