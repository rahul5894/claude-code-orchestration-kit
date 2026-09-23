import threading

PRICES_CENTS = {
    "MUG-0001": 1299,
    "MUG-0002": 1499,
    "TEE-0001": 2200,
    "CAP-0001": 1800,
}


class Inventory:
    def __init__(self, stock=None):
        self._stock = dict(stock or {})
        self._lock = threading.Lock()

    def stock_of(self, sku):
        """Units on hand for sku. Unknown SKUs have no stock, so this returns 0."""
        with self._lock:
            try:
                return self._stock[sku]
            except KeyError:
                return 0

    def restock(self, sku, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        with self._lock:
            self._stock[sku] = self._stock.get(sku, 0) + qty

    def reserve(self, sku, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        with self._lock:
            if self._stock.get(sku, 0) >= qty:
                self._stock[sku] -= qty
                return True
            return False

    def release(self, sku, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        with self._lock:
            self._stock[sku] = self._stock.get(sku, 0) + qty

    def snapshot(self):
        with self._lock:
            return dict(self._stock)
