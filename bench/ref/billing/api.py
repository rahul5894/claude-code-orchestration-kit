"""Request handlers. A request is a dict; every handler returns a dict with an HTTP-like
"status". Callers authenticate with "api_key"; "actor" is who acts: a customer's email, or
"staff:<name>" for staff."""
import functools
import hmac
import logging
import os
import re

from billing import customers, dates, invoices, subscriptions

logger = logging.getLogger(__name__)

API_KEY = os.environ.get("BILLING_API_KEY", "")


class BadRequest(Exception):
    pass


def _authorized(request):
    given = request.get("api_key")
    return bool(API_KEY) and isinstance(given, str) and hmac.compare_digest(
        given.encode(), API_KEY.encode())


def _is_staff(actor):
    return isinstance(actor, str) and actor.startswith("staff:")


def _int(value, name, low=1, high=2**63 - 1):
    """A request value as an int in [low, high]; digit strings are accepted, bools are not."""
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,19}", value):
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise BadRequest(f"invalid {name}")
    return value


def handler(fn):
    """Every handler: a dict request, a valid api key, and no exception or internal detail
    ever leaves it."""
    @functools.wraps(fn)
    def wrapped(conn, request):
        if not isinstance(request, dict) or not _authorized(request):
            return {"status": 403}
        try:
            return fn(conn, request)
        except BadRequest as exc:
            return {"status": 400, "error": str(exc)}
        except Exception:
            logger.exception("%s failed", fn.__name__)
            return {"status": 500, "error": "internal error"}
    return wrapped


@handler
def create_customer(conn, request):
    """201 {"customer_id"}; 400 {"error"} for bad input; 403 without a valid api key.
    Only staff may create customers."""
    if not _is_staff(request.get("actor")):
        return {"status": 403}
    try:
        customer_id = customers.create_customer(
            conn, request.get("email"), request.get("name"), request.get("region")
        )
    except customers.CustomerError as exc:
        return {"status": 400, "error": str(exc)}
    return {"status": 201, "customer_id": customer_id}


@handler
def get_invoice(conn, request):
    """200 {"invoice"}; 400 for a bad "invoice_id"; 403 without a valid api key; 404 for an
    unknown invoice. A customer may read only their own invoices, staff any."""
    invoice = invoices.get_invoice(conn, _int(request.get("invoice_id"), "invoice_id"))
    if invoice is None:
        return {"status": 404}
    owner = customers.get_customer(conn, invoice["customer_id"])
    if not customers.may_act_for(request.get("actor"), owner["email"]):
        return {"status": 404}
    return {"status": 200, "invoice": invoice}


@handler
def pay_invoice(conn, request):
    """200 {"paid": true}; 400 for a bad "invoice_id"; 403; 404 unknown; 409 when the invoice is
    not open. Staff only."""
    if not _is_staff(request.get("actor")):
        return {"status": 403}
    invoice_id = _int(request.get("invoice_id"), "invoice_id")
    if invoices.get_invoice(conn, invoice_id) is None:
        return {"status": 404}
    if not invoices.mark_paid(conn, invoice_id):
        return {"status": 409}
    return {"status": 200, "paid": True}


@handler
def change_plan(conn, request):
    """200 {change_plan's dict}; 400 malformed or disallowed; 403 bad key or actor; 404
    unknown subscription."""
    subscription_id = _int(request.get("subscription_id"), "subscription_id")
    plan = request.get("plan")
    if not isinstance(plan, str):
        raise BadRequest("invalid plan")
    on = request.get("on")
    try:
        on = dates.utc_today() if on is None else dates.parse_date(on)
    except ValueError:
        raise BadRequest("invalid on") from None
    try:
        result = subscriptions.change_plan(conn, subscription_id, plan, request.get("actor"), on)
    except subscriptions.SubscriptionNotFound:
        return {"status": 404}
    except subscriptions.NotAllowed:
        return {"status": 403}
    except subscriptions.SubscriptionError as exc:
        return {"status": 400, "error": str(exc)}
    return {"status": 200, **result}


@handler
def statement(conn, request):
    """200 {"invoices", "next_cursor"}: a customer's invoices newest first, keyset-paged."""
    customer_id = _int(request.get("customer_id"), "customer_id")
    limit = _int(request.get("limit", 20), "limit", 1, 100)
    cursor = request.get("cursor")
    before = None if cursor is None else _int(cursor, "cursor")
    customer = customers.get_customer(conn, customer_id)
    if customer is None:
        return {"status": 404}
    if not customers.may_act_for(request.get("actor"), customer["email"]):
        return {"status": 403}
    rows = invoices.statement_page(conn, customer_id, limit + 1, before)
    page = rows[:limit]
    return {
        "status": 200,
        "invoices": [{k: r[k] for k in ("number", "issued_on", "total_cents", "status")}
                     for r in page],
        "next_cursor": str(page[-1]["id"]) if len(rows) > limit else None,
    }
