import os

INVOICE_DIR = os.environ.get(
    "SHOP_INVOICE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "invoices"),
)


def invoice_name(order_id):
    return f"invoice-{int(order_id):06d}.pdf"


def write_invoice(order_id, data):
    os.makedirs(INVOICE_DIR, exist_ok=True)
    path = os.path.join(INVOICE_DIR, invoice_name(order_id))
    with open(path, "wb") as f:
        f.write(data)
    return path


def list_invoices():
    if not os.path.isdir(INVOICE_DIR):
        return []
    return sorted(n for n in os.listdir(INVOICE_DIR) if n.endswith(".pdf"))


def read_invoice(name):
    base = os.path.realpath(INVOICE_DIR)
    path = os.path.realpath(os.path.join(base, name))
    if os.path.dirname(path) != base:
        raise ValueError("invalid invoice name")
    with open(path, "rb") as f:
        return f.read()
