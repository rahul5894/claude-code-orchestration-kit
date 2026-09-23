"""Request handlers. A request is a dict; every handler returns a dict with an HTTP-like
"status". Callers authenticate with "api_key"; "actor" is who acts: a customer's email, or
"staff:<name>" for staff."""
import logging
import os
import traceback

from billing import customers, invoices

logger = logging.getLogger(__name__)

API_KEY = os.environ.get("BILLING_API_KEY", "")


def _authorized(request):
    return request.get("api_key") == API_KEY


def _is_staff(actor):
    return isinstance(actor, str) and actor.startswith("staff:")


def create_customer(conn, request):
    """201 {"customer_id"}; 400 {"error"} for bad input; 403 without a valid api key.
    Only staff may create customers."""
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
        logger.exception("create_customer failed")
        return {"status": 500, "error": traceback.format_exc()}
    return {"status": 201, "customer_id": customer_id}


def get_invoice(conn, request):
    """200 {"invoice"}; 400 for a bad "invoice_id"; 403 without a valid api key; 404 for an
    unknown invoice. A customer may read only their own invoices, staff any."""
    if not _authorized(request):
        return {"status": 403}
    try:
        invoice = invoices.get_invoice(conn, int(request["invoice_id"]))
    except Exception:
        logger.exception("get_invoice failed")
        return {"status": 500, "error": traceback.format_exc()}
    if invoice is None:
        return {"status": 404}
    return {"status": 200, "invoice": invoice}


def pay_invoice(conn, request):
    """200 {"paid": true}; 400 for a bad "invoice_id"; 403; 404 unknown; 409 when the invoice is
    not open. Staff only."""
    if not _authorized(request):
        return {"status": 403}
    if not _is_staff(request.get("actor")):
        return {"status": 403}
    try:
        invoice_id = int(request["invoice_id"])
    except Exception:
        logger.exception("pay_invoice failed")
        return {"status": 500, "error": traceback.format_exc()}
    if invoices.get_invoice(conn, invoice_id) is None:
        return {"status": 404}
    if not invoices.mark_paid(conn, invoice_id):
        return {"status": 409}
    return {"status": 200, "paid": True}
