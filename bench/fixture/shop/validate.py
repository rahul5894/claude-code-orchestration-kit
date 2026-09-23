import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$")
MAX_QTY = 100


def email_ok(value):
    return bool(EMAIL_RE.match(value or ""))


def qty_ok(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value <= MAX_QTY


def customer_ok(value):
    return isinstance(value, str) and 0 < len(value.strip()) <= 80
