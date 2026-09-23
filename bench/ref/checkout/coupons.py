import datetime
import re
import sqlite3

CODE_RE = re.compile(r"[A-Za-z0-9-]{3,20}")


class CouponError(Exception):
    pass


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_staff(actor):
    return isinstance(actor, str) and actor.startswith("staff:")


def normalize(code):
    if not isinstance(code, str) or not CODE_RE.fullmatch(code):
        raise CouponError("invalid coupon code")
    return code.upper()


def create_coupon(conn, actor, code, kind, value, min_total_cents=0, expires_on=None,
                  max_redemptions=None):
    if not is_staff(actor):
        raise CouponError("only staff may create coupons")
    code = normalize(code)
    if kind == "percent":
        valid = _is_int(value) and 1 <= value <= 100
    else:
        valid = kind == "fixed" and _is_int(value) and value > 0
    if not valid:
        raise CouponError("invalid kind or value")
    if not _is_int(min_total_cents) or min_total_cents < 0:
        raise CouponError("invalid min_total_cents")
    if expires_on is not None and not isinstance(expires_on, datetime.date):
        raise CouponError("invalid expires_on")
    if max_redemptions is not None and (not _is_int(max_redemptions) or max_redemptions < 1):
        raise CouponError("invalid max_redemptions")
    try:
        with conn:
            conn.execute(
                "INSERT INTO coupons (code, kind, value, min_total_cents, expires_on, max_redemptions)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (code, kind, value, min_total_cents,
                 expires_on.isoformat() if expires_on else None, max_redemptions),
            )
    except sqlite3.IntegrityError:
        raise CouponError(f"coupon {code} already exists") from None
    return code


def get_coupon(conn, code):
    row = conn.execute("SELECT * FROM coupons WHERE code = ?", (normalize(code),)).fetchone()
    return dict(row) if row else None


def redemption_count(conn, code):
    if get_coupon(conn, code) is None:
        raise CouponError("unknown coupon")
    return conn.execute(
        "SELECT COUNT(*) FROM redemptions WHERE code = ?", (normalize(code),)
    ).fetchone()[0]
