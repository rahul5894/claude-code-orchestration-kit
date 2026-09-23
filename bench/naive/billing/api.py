import datetime
import logging
import os
import traceback

from billing import customers, invoices, subscriptions

logger = logging.getLogger(__name__)

API_KEY = os.environ.get("BILLING_API_KEY", "")


def _authorized(request):
    return request.get("api_key") == API_KEY


def _is_staff(actor):
    return isinstance(actor, str) and actor.startswith("staff:")


def create_customer(conn, request):
    if not _authorized(request):
        return {"status": 403}
    if not _is_staff(request.get("actor")):
        return {"status": 403}
    try:
        customer_id = customers.create_customer(
            conn, request.get("email"), request.get("name"), request.get("region")
        )
    except customers.CustomerError as exc:
        return {"status": 400, "error": str(exc)}
    except Exception:
        return {"status": 500, "error": traceback.format_exc()}
    return {"status": 201, "customer_id": customer_id}


def get_invoice(conn, request):
    if not _authorized(request):
        return {"status": 403}
    try:
        invoice = invoices.get_invoice(conn, int(request["invoice_id"]))
    except Exception:
        return {"status": 500, "error": traceback.format_exc()}
    if invoice is None:
        return {"status": 404}
    return {"status": 200, "invoice": invoice}


def pay_invoice(conn, request):
    if not _authorized(request):
        return {"status": 403}
    if not _is_staff(request.get("actor")):
        return {"status": 403}
    try:
        invoice_id = int(request["invoice_id"])
    except Exception:
        return {"status": 500, "error": traceback.format_exc()}
    if invoices.get_invoice(conn, invoice_id) is None:
        return {"status": 404}
    if not invoices.mark_paid(conn, invoice_id):
        return {"status": 409}
    return {"status": 200, "paid": True}


def change_plan(conn, request):
    if not _authorized(request):
        return {"status": 403}
    try:
        sid = int(request["subscription_id"])
        on = request.get("on")
        on = datetime.date.fromisoformat(on) if on else datetime.date.today()
    except Exception:
        return {"status": 400, "error": "bad request"}
    sub = subscriptions.get_subscription(conn, sid)
    if sub is None:
        return {"status": 404}
    cust = customers.get_customer(conn, sub["customer_id"])
    actor = request.get("actor")
    if not (_is_staff(actor) or actor == cust["email"]):
        return {"status": 403}
    try:
        result = subscriptions.change_plan(conn, sid, request.get("plan"), actor, on)
    except subscriptions.SubscriptionError as exc:
        return {"status": 400, "error": str(exc)}
    return dict(result, status=200)


def statement(conn, request):
    if not _authorized(request):
        return {"status": 403}
    try:
        cid = int(request["customer_id"])
        limit = int(request.get("limit", 20))
        offset = int(request.get("cursor") or 0)
    except Exception:
        return {"status": 400, "error": "bad request"}
    if limit < 1 or limit > 100:
        return {"status": 400, "error": "bad limit"}
    cust = customers.get_customer(conn, cid)
    if cust is None:
        return {"status": 404}
    actor = request.get("actor")
    if not (_is_staff(actor) or actor == cust["email"]):
        return {"status": 403}
    rows = conn.execute(
        "SELECT number, issued_on, total_cents, status FROM invoices WHERE customer_id = ?"
        " ORDER BY id DESC LIMIT ? OFFSET ?", (cid, limit + 1, offset)).fetchall()
    nxt = str(offset + limit) if len(rows) > limit else None
    return {"status": 200, "invoices": [dict(r) for r in rows[:limit]], "next_cursor": nxt}
