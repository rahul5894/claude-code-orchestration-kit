"""Shared setup for the billing hidden tests: imports `billing` from BENCH_REPO, one file DB per
test (threads open their own connections to it)."""
import datetime
import os
import shutil
import sys
import tempfile
import threading
import unittest

REPO = os.environ.get("BENCH_REPO", "")
sys.path.insert(0, REPO)
KEY = "bench-key"
os.environ["BILLING_API_KEY"] = KEY
D = datetime.date

try:
    from billing import (api, customers, dates, db, invoices, money,  # noqa: F401
                         proration, subscriptions, tax)
    IMPORT_ERROR = None
except Exception as exc:  # the untouched fixture, or a broken arm, scores 0 instead of crashing
    IMPORT_ERROR = exc


class Base(unittest.TestCase):
    def setUp(self):
        if IMPORT_ERROR is not None:
            self.fail(f"import billing failed: {IMPORT_ERROR!r}")
        self.dir = tempfile.mkdtemp(prefix="bench-billing-")
        self.path = os.path.join(self.dir, "billing.db")
        self.conn = db.connect(self.path)

    def tearDown(self):
        conn = getattr(self, "conn", None)
        if conn is not None:
            conn.close()
        shutil.rmtree(getattr(self, "dir", ""), ignore_errors=True)

    def connect(self):
        conn = db.connect(self.path)
        self.addCleanup(conn.close)
        return conn

    def customer(self, email="ann@example.com", region="GB"):
        return customers.create_customer(self.conn, email, "Ann", region)

    def subscribe(self, cid, plan="team", start=D(2025, 3, 1)):
        return subscriptions.subscribe(self.conn, cid, plan, start)

    def count(self, table):
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def sub(self, sid):
        return dict(self.conn.execute("SELECT * FROM subscriptions WHERE id = ?", (sid,)).fetchone())

    def credit(self, cid):
        return self.conn.execute("SELECT credit_cents FROM customers WHERE id = ?", (cid,)).fetchone()[0]

    def lines(self, invoice_id):
        return [(r[0], r[1]) for r in self.conn.execute(
            "SELECT description, amount_cents FROM invoice_lines WHERE invoice_id = ? ORDER BY id",
            (invoice_id,))]

    def invoice(self, invoice_id):
        return dict(self.conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone())

    def state(self):
        """Everything a refused call must leave as it was."""
        return [list(map(tuple, self.conn.execute(f"SELECT * FROM {t} ORDER BY id")))
                for t in ("customers", "subscriptions", "invoices", "invoice_lines")]


def run_together(fns):
    """Start every fn at once on its own thread; return [(result, exception)] in order."""
    barrier = threading.Barrier(len(fns))
    out = [None] * len(fns)

    def go(i, fn):
        barrier.wait()
        try:
            out[i] = (fn(), None)
        except Exception as exc:
            out[i] = (None, exc)

    threads = [threading.Thread(target=go, args=(i, fn)) for i, fn in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    return out
