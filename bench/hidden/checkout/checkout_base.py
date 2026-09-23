"""Shared setup for the checkout ticket's hidden tests. Run through score.py; BENCH_REPO names
the repo. Every test is written from the ticket text alone."""
import datetime
import os
import shutil
import sys
import tempfile
import unittest

REPO = os.environ.get("BENCH_REPO")
if REPO:
    sys.path.insert(0, os.path.abspath(REPO))
os.environ.setdefault("SHOP_API_KEY", "bench-key")

try:
    from shop import api, checkout, coupons, db, orders
    from shop.inventory import PRICES_CENTS

    IMPORT_ERROR = None
except Exception as exc:  # the untouched base has no shop.checkout / shop.coupons
    api = checkout = coupons = db = orders = PRICES_CENTS = None
    IMPORT_ERROR = exc

OWNER = "ana@example.com"
STAFF = "staff:7"
TODAY = datetime.date(2099, 3, 10)  # future: creating an already-expired coupon may be refused


class Base(unittest.TestCase):
    def setUp(self):
        if IMPORT_ERROR is not None:
            raise IMPORT_ERROR
        self.dir = tempfile.mkdtemp(prefix="bench-checkout-")
        self.conns = []
        self.conn = self.connect("shop.db")
        self.stock_before = api.INVENTORY.snapshot()

    def tearDown(self):
        # every test leaves the shared inventory as it found it
        for sku, qty in api.INVENTORY.snapshot().items():
            diff = self.stock_before.get(sku, 0) - qty
            if diff > 0:
                api.INVENTORY.restock(sku, diff)
            elif diff < 0:
                api.INVENTORY.reserve(sku, -diff)
        for conn in self.conns:
            try:
                conn.close()
            except Exception:
                pass
        shutil.rmtree(self.dir, ignore_errors=True)

    def connect(self, name):
        conn = db.connect(os.path.join(self.dir, name))
        self.conns.append(conn)
        return conn

    def order(self, lines=(("MUG-0001", 2),), email=OWNER, conn=None):
        """An order in status "new". Prices come from PRICES_CENTS, as api.create_order does."""
        items = [{"sku": s, "qty": q, "price_cents": PRICES_CENTS[s]} for s, q in lines]
        return db.save_order(conn or self.conn, "Ana", email, items)

    def status(self, order_id, conn=None):
        return orders.get_order(conn or self.conn, order_id)["status"]

    def stock(self, sku):
        return api.INVENTORY.stock_of(sku)
