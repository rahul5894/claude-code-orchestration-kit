"""What the ticket asks for: change_plan, run_billing, api.change_plan, api.statement."""
from billing_base import KEY, Base, D, api, subscriptions


class ChangePlan(Base):
    def test_upgrade_invoices_two_lines(self):
        cid = self.customer()
        sid = self.subscribe(cid, "team", D(2025, 3, 1))  # 31-day period, 15 days left on 3/17
        r = subscriptions.change_plan(self.conn, sid, "business", "ann@example.com", D(2025, 3, 17))
        self.assertEqual(r["plan"], "business")
        self.assertEqual(r["subscription_id"], sid)
        self.assertEqual(r["credit_added_cents"], 0)
        self.assertIsInstance(r["invoice_id"], int)
        self.assertEqual(self.lines(r["invoice_id"]),
                         [("Unused time on team", -1403), ("Remaining time on business", 4790)])
        inv = self.invoice(r["invoice_id"])
        self.assertEqual((inv["issued_on"], inv["subtotal_cents"], inv["tax_cents"], inv["total_cents"]),
                         ("2025-03-17", 3387, 677, 4064))
        sub = self.sub(sid)
        self.assertEqual((sub["plan"], sub["period_start"], sub["period_end"]),
                         ("business", "2025-03-01", "2025-04-01"))

    def test_downgrade_adds_credit_no_invoice(self):
        cid = self.customer()
        sid = self.subscribe(cid, "business", D(2025, 3, 1))
        before = self.count("invoices")
        r = subscriptions.change_plan(self.conn, sid, "basic", "staff:bo", D(2025, 3, 17))
        self.assertIsNone(r["invoice_id"])
        self.assertEqual(r["credit_added_cents"], 4790 - 435)
        self.assertEqual(self.credit(cid), 4355)
        self.assertEqual(self.count("invoices"), before)
        self.assertEqual(self.sub(sid)["plan"], "basic")

    def test_february_period_uses_its_real_length(self):
        cid = self.customer()
        sid = self.subscribe(cid, "team", D(2025, 2, 1))  # 28 days, 14 left on 2/15
        r = subscriptions.change_plan(self.conn, sid, "business", "ann@example.com", D(2025, 2, 15))
        self.assertEqual(self.lines(r["invoice_id"]),
                         [("Unused time on team", -1450), ("Remaining time on business", 4950)])

    def test_actor_email_any_case(self):
        cid = self.customer()
        sid = self.subscribe(cid)
        r = subscriptions.change_plan(self.conn, sid, "business", "ANN@Example.COM", D(2025, 3, 2))
        self.assertEqual(r["plan"], "business")

    def test_refusals_change_nothing(self):
        cid = self.customer()
        self.customer("bob@example.com")
        sid = self.subscribe(cid)
        gone = self.subscribe(cid, "basic")
        subscriptions.cancel(self.conn, gone)
        cases = [
            (sid, "business", "bob@example.com", D(2025, 3, 5)),   # another customer
            (sid, "team", "ann@example.com", D(2025, 3, 5)),       # same plan
            (sid, "gold", "ann@example.com", D(2025, 3, 5)),       # unknown plan
            (gone, "team", "ann@example.com", D(2025, 3, 5)),      # cancelled
            (sid, "business", "ann@example.com", D(2025, 2, 28)),  # before the period
            (sid, "business", "ann@example.com", D(2025, 4, 1)),   # period_end is outside
            (10**6, "business", "staff:x", D(2025, 3, 5)),         # unknown subscription
        ]
        for args in cases:
            with self.subTest(args=args):
                before = self.state()
                with self.assertRaises(subscriptions.SubscriptionError):
                    subscriptions.change_plan(self.conn, *args)
                self.assertEqual(self.state(), before)

    def test_subscription_started_on_the_31st(self):
        cid = self.customer()
        sid = self.subscribe(cid, "basic", D(2025, 1, 31))
        self.assertEqual(self.sub(sid)["period_end"], "2025-02-28")


class RunBilling(Base):
    def test_renews_one_period(self):
        cid = self.customer()
        sid = self.subscribe(cid, "team", D(2025, 3, 1))
        ids = subscriptions.run_billing(self.conn, D(2025, 4, 1))
        self.assertEqual(len(ids), 1)
        self.assertEqual(self.lines(ids[0]), [("Plan team 2025-04-01 to 2025-05-01", 2900)])
        inv = self.invoice(ids[0])
        self.assertEqual((inv["issued_on"], inv["subscription_id"], inv["total_cents"]),
                         ("2025-04-01", sid, 3480))
        sub = self.sub(sid)
        self.assertEqual((sub["period_start"], sub["period_end"]), ("2025-04-01", "2025-05-01"))

    def test_not_due_yet(self):
        self.subscribe(self.customer(), "team", D(2025, 3, 1))
        self.assertEqual(subscriptions.run_billing(self.conn, D(2025, 3, 31)), [])

    def test_catch_up_keeps_the_anchor_day(self):
        cid = self.customer()
        sid = self.subscribe(cid, "basic", D(2025, 1, 31))
        ids = subscriptions.run_billing(self.conn, D(2025, 3, 31))
        self.assertEqual([self.lines(i) for i in ids], [
            [("Plan basic 2025-02-28 to 2025-03-31", 900)],
            [("Plan basic 2025-03-31 to 2025-04-30", 900)],
        ])
        self.assertEqual([self.invoice(i)["issued_on"] for i in ids], ["2025-02-28", "2025-03-31"])
        sub = self.sub(sid)
        self.assertEqual((sub["period_start"], sub["period_end"]), ("2025-03-31", "2025-04-30"))

    def test_credit_is_applied_then_used_up(self):
        cid = self.customer()
        self.subscribe(cid, "basic", D(2025, 3, 1))
        self.conn.execute("UPDATE customers SET credit_cents = 1000 WHERE id = ?", (cid,))
        self.conn.commit()
        ids = subscriptions.run_billing(self.conn, D(2025, 5, 1))
        self.assertEqual([self.lines(i) for i in ids], [
            [("Plan basic 2025-04-01 to 2025-05-01", 900), ("Credit applied", -900)],
            [("Plan basic 2025-05-01 to 2025-06-01", 900), ("Credit applied", -100)],
        ])
        self.assertEqual([self.invoice(i)["total_cents"] for i in ids], [0, 960])
        self.assertEqual(self.credit(cid), 0)

    def test_cancelled_is_never_billed(self):
        sid = self.subscribe(self.customer())
        subscriptions.cancel(self.conn, sid)
        self.assertEqual(subscriptions.run_billing(self.conn, D(2025, 9, 1)), [])

    def test_second_run_same_day_issues_nothing(self):
        self.subscribe(self.customer())
        first = subscriptions.run_billing(self.conn, D(2025, 4, 1))
        n = self.count("invoices")
        self.assertEqual(len(first), 1)
        self.assertEqual(subscriptions.run_billing(self.conn, D(2025, 4, 1)), [])
        self.assertEqual(self.count("invoices"), n)

    def test_returns_ids_in_issue_order(self):
        cid = self.customer()
        self.subscribe(cid, "team", D(2025, 3, 1))
        self.subscribe(cid, "basic", D(2025, 1, 10))  # two periods due by 4/1
        ids = subscriptions.run_billing(self.conn, D(2025, 4, 1))
        self.assertEqual(len(ids), 3)
        self.assertEqual(ids, sorted(ids))


class Api(Base):
    def req(self, **kw):
        return {"api_key": KEY, **kw}

    def test_change_plan_ok(self):
        cid = self.customer()
        sid = self.subscribe(cid)
        r = api.change_plan(self.conn, self.req(actor="ann@example.com", subscription_id=sid,
                                                plan="business", on="2025-03-17"))
        self.assertEqual(r["status"], 200)
        self.assertEqual((r["plan"], r["subscription_id"], r["credit_added_cents"]), ("business", sid, 0))
        self.assertIsInstance(r["invoice_id"], int)

    def test_change_plan_errors(self):
        cid = self.customer()
        self.customer("bob@example.com")
        sid = self.subscribe(cid)
        base = {"actor": "ann@example.com", "subscription_id": sid, "plan": "business", "on": "2025-03-17"}
        cases = [
            (400, {"on": "2025-13-01"}),
            (400, {"plan": "team"}),
            (404, {"subscription_id": 10**6, "actor": "staff:x"}),
            (403, {"api_key": "wrong"}),
            (403, {"actor": "bob@example.com"}),
        ]
        for status, change in cases:
            with self.subTest(change=change):
                self.assertEqual(api.change_plan(self.conn, self.req(**{**base, **change}))["status"], status)

    def make_invoices(self, n):
        cid = self.customer()
        sid = self.subscribe(cid, "basic", D(2025, 1, 1))
        subscriptions.run_billing(self.conn, D(2025, n, 1))
        return cid, sid

    def test_statement_pages_newest_first(self):
        cid, _ = self.make_invoices(5)  # 5 invoices
        numbers, cursor, pages = [], None, 0
        while True:
            req = self.req(actor="ann@example.com", customer_id=cid, limit=2)
            if cursor is not None:
                req["cursor"] = cursor
            r = api.statement(self.conn, req)
            self.assertEqual(r["status"], 200)
            pages += 1
            for inv in r["invoices"]:
                self.assertEqual(set(inv), {"number", "issued_on", "total_cents", "status"})
            numbers += [inv["number"] for inv in r["invoices"]]
            cursor = r["next_cursor"]
            if cursor is None:
                break
            self.assertIsInstance(cursor, str)
            self.assertLess(pages, 10)
        self.assertEqual(pages, 3)
        self.assertEqual(numbers, sorted(numbers, reverse=True))
        self.assertEqual(len(set(numbers)), 5)

    def test_statement_stable_when_invoices_arrive_between_pages(self):
        cid, _ = self.make_invoices(5)
        r1 = api.statement(self.conn, self.req(actor="staff:x", customer_id=cid, limit=2))
        self.subscribe(cid, "team", D(2025, 6, 1))  # a new invoice between the two pages
        r2 = api.statement(self.conn, self.req(actor="staff:x", customer_id=cid, limit=2,
                                               cursor=r1["next_cursor"]))
        first = [i["number"] for i in r1["invoices"]]
        second = [i["number"] for i in r2["invoices"]]
        self.assertFalse(set(first) & set(second))
        self.assertTrue(all(b < a for a in first for b in second))

    def test_statement_errors(self):
        cid, _ = self.make_invoices(2)
        self.customer("bob@example.com")
        cases = [
            (400, {"limit": 0}), (400, {"limit": 101}), (400, {"limit": "x"}),
            (400, {"cursor": "zzz"}),
            (404, {"customer_id": 10**6, "actor": "staff:x"}),
            (403, {"actor": "bob@example.com"}),
            (403, {"api_key": "nope"}),
        ]
        for status, change in cases:
            with self.subTest(change=change):
                req = self.req(**{"actor": "ann@example.com", "customer_id": cid, **change})
                self.assertEqual(api.statement(self.conn, req)["status"], status)
