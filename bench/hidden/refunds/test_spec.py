"""Hidden tests for the refunds ticket. Run through score.py; BENCH_REPO names the repo."""
import inspect
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
import uuid

REPO = os.environ.get("BENCH_REPO")
if REPO:
    sys.path.insert(0, os.path.abspath(REPO))
os.environ.setdefault("SHOP_API_KEY", "bench-key")

try:
    from shop import api, db, refunds
    from shop.inventory import PRICES_CENTS

    IMPORT_ERROR = None
except Exception as exc:  # the untouched base has no shop.refunds
    IMPORT_ERROR = exc

OWNER = "ana@example.com"


class RefundCase(unittest.TestCase):
    def setUp(self):
        if IMPORT_ERROR is not None:
            raise IMPORT_ERROR
        self.dir = tempfile.mkdtemp(prefix="bench-refunds-")
        self.path = os.path.join(self.dir, "shop.db")
        self.conns = []
        self.conn = self.connect()
        self.order_id = self.make_order([("MUG-0001", 1, 100)])  # total 100 cents

    def tearDown(self):
        for conn in self.conns:
            try:
                conn.close()
            except Exception:
                pass
        shutil.rmtree(self.dir, ignore_errors=True)

    def connect(self):
        conn = db.connect(self.path)
        self.conns.append(conn)
        return conn

    def make_order(self, lines, email=OWNER):
        items = [{"sku": s, "qty": q, "price_cents": p} for s, q, p in lines]
        order_id = db.save_order(self.conn, "Ana", email, items)
        # v2: the ticket is silent on order status; a paid order is refundable under every
        # reasonable reading ("new" = no money captured yet was a defensible refusal).
        self.conn.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (order_id,))
        self.conn.commit()
        return order_id

    def refund(self, amount, key=None, actor=OWNER, order_id=None, conn=None):
        return refunds.refund(
            conn or self.conn,
            self.order_id if order_id is None else order_id,
            amount,
            key or uuid.uuid4().hex,
            actor,
        )

    def refund_rows(self):
        """Committed rows in the largest table whose name contains 'refund'."""
        conn = sqlite3.connect(self.path)
        try:
            names = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                    " AND lower(name) LIKE '%refund%'"
                )
            ]
            return max(
                (conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names),
                default=0,
            )
        finally:
            conn.close()

    def run_threads(self, n, amount, key_of):
        # A live service has refunded before: warm up on another order so a lazily
        # created table exists and the threads race the refund, not the DDL.
        self.refund(1, order_id=self.make_order([("CAP-0001", 1, 100)]))
        barrier = threading.Barrier(n)
        out = []

        def worker(i):
            try:
                conn = self.connect()
                barrier.wait(timeout=30)
                out.append(("ok", self.refund(amount, key_of(i), conn=conn)))
            except refunds.RefundError:
                out.append(("refused", None))
            except Exception as exc:
                out.append(("crash", repr(exc)))

        threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        self.assertFalse(any(t.is_alive() for t in threads), "a refund thread hung")
        self.assertEqual([o for o in out if o[0] == "crash"], [])
        return [r for kind, r in out if kind == "ok"]

    def call_handler(self, request):
        # The ticket names api.refund_order(request); the other DB handlers take
        # (conn, request). Accept either shape.
        if len(inspect.signature(api.refund_order).parameters) >= 2:
            return api.refund_order(self.conn, request)
        return api.refund_order(request)


class RefundTests(RefundCase):
    def test_partial_refunds_up_to_total_then_one_more_cent_raises(self):
        results = [self.refund(a) for a in (30, 30, 40)]
        for r, amount in zip(results, (30, 30, 40)):
            self.assertLessEqual({"refund_id", "order_id", "amount_cents", "status"}, set(r))
            self.assertEqual((r["order_id"], r["amount_cents"]), (self.order_id, amount))
        self.assertEqual(len({r["refund_id"] for r in results}), 3)
        with self.assertRaises(refunds.RefundError):
            self.refund(1)

    def test_zero_amount_raises(self):
        with self.assertRaises(refunds.RefundError):
            self.refund(0)

    def test_negative_amount_raises(self):
        with self.assertRaises(refunds.RefundError):
            self.refund(-10)

    def test_float_amount_raises(self):
        with self.assertRaises(refunds.RefundError):
            self.refund(10.0)

    def test_bool_amount_raises(self):
        with self.assertRaises(refunds.RefundError):
            self.refund(True)

    def test_same_key_twice_returns_same_refund_and_counts_once(self):
        first = self.refund(30, "retry-1")
        again = self.refund(30, "retry-1")
        self.assertEqual(first["refund_id"], again["refund_id"])
        self.refund(70)  # exceeds the total if the retry counted twice

    def test_same_key_different_amount_raises(self):
        self.refund(30, "retry-1")
        with self.assertRaises(refunds.RefundError):
            self.refund(40, "retry-1")

    def test_concurrent_distinct_keys_never_exceed_total(self):
        ok = self.run_threads(20, 10, lambda i: f"key-{i}")
        self.assertEqual(len(ok), 10)
        self.assertEqual(sum(r["amount_cents"] for r in ok), 100)
        self.assertEqual(self.refund_rows(), 1 + 10)  # warm-up + 10

    def test_concurrent_same_key_records_one_refund(self):
        ok = self.run_threads(10, 10, lambda i: "same-key")
        self.assertGreaterEqual(len(ok), 1)
        self.assertEqual(len({r["refund_id"] for r in ok}), 1)
        self.assertEqual(self.refund_rows(), 1 + 1)  # warm-up + 1

    def test_wrong_actor_raises(self):
        with self.assertRaises(refunds.RefundError):
            self.refund(10, actor="eve@example.com")

    def test_owner_and_staff_may_refund(self):
        self.assertEqual(self.refund(10, actor=OWNER)["amount_cents"], 10)
        self.assertEqual(self.refund(10, actor="staff:x")["amount_cents"], 10)

    def test_unknown_order_raises(self):
        with self.assertRaises(refunds.RefundError):
            self.refund(10, order_id=999999)

    def test_full_refund_restocks_inventory(self):
        lines = [("MUG-0002", 2, PRICES_CENTS["MUG-0002"]), ("CAP-0001", 1, PRICES_CENTS["CAP-0001"])]
        order_id = self.make_order(lines)
        total = sum(q * p for _, q, p in lines)
        before = {s: api.INVENTORY.stock_of(s) for s, _, _ in lines}
        self.refund(1000, order_id=order_id)
        self.refund(total - 1000, order_id=order_id)
        after = {s: api.INVENTORY.stock_of(s) for s, _, _ in lines}
        self.assertEqual(after, {s: before[s] + q for s, q, _ in lines})

    def test_partial_refund_does_not_restock(self):
        lines = [("TEE-0001", 3, PRICES_CENTS["TEE-0001"])]
        order_id = self.make_order(lines)
        before = api.INVENTORY.stock_of("TEE-0001")
        self.refund(3 * PRICES_CENTS["TEE-0001"] - 1, order_id=order_id)
        self.assertEqual(api.INVENTORY.stock_of("TEE-0001"), before)

    def test_one_row_per_successful_refund_none_for_failed(self):
        for amount in (10, 20, 30):
            self.refund(amount)
        for call in (
            lambda: self.refund(0),
            lambda: self.refund(10, actor="eve@example.com"),
            lambda: self.refund(50),
        ):
            with self.assertRaises(refunds.RefundError):
                call()
        self.assertEqual(self.refund_rows(), 3)

    def test_api_bad_key_returns_403(self):
        request = {"api_key": "wrong-key", "order_id": self.order_id, "amount_cents": 10,
                   "idempotency_key": "api-1", "actor": OWNER}
        self.assertEqual(self.call_handler(request), {"status": 403})

    def test_api_refund_error_returns_400(self):
        request = {"api_key": os.environ["SHOP_API_KEY"], "order_id": self.order_id,
                   "amount_cents": 0, "idempotency_key": "api-2", "actor": OWNER}
        result = self.call_handler(request)
        self.assertEqual(set(result), {"status", "error"})
        self.assertEqual(result["status"], 400)
        self.assertIsInstance(result["error"], str)


if __name__ == "__main__":
    unittest.main()
