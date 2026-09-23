import datetime
import hmac
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from shop import checkout, coupons, db, files, orders
from shop.inventory import PRICES_CENTS, Inventory
from shop.notify import EmailNotifier
from shop.validate import customer_ok, email_ok, qty_ok

logger = logging.getLogger(__name__)

API_KEY = os.environ["SHOP_API_KEY"]

INVENTORY = Inventory({"MUG-0001": 40, "MUG-0002": 25, "TEE-0001": 60, "CAP-0001": 30})


def check_api_key(given):
    if not isinstance(given, str):
        return False
    return hmac.compare_digest(given.encode(), API_KEY.encode())


def login(request, authenticate):
    logger.info("login %s", request.get("username", ""))
    user = authenticate(request.get("username", ""), request.get("password", ""))
    if user is None:
        return {"status": 401, "error": "invalid credentials"}
    return {"status": 200, "user": user}


def create_order(conn, request):
    customer = request.get("customer")
    email = request.get("email", "")
    items = request.get("items") or []
    if not customer_ok(customer):
        return {"status": 400, "error": "invalid customer"}
    if not email_ok(email):
        return {"status": 400, "error": "invalid email"}
    if not items or not all(
        i.get("sku") in PRICES_CENTS and qty_ok(i.get("qty")) for i in items
    ):
        return {"status": 400, "error": "invalid items"}
    lines = [
        {"sku": i["sku"], "qty": i["qty"], "price_cents": PRICES_CENTS[i["sku"]]}
        for i in items
    ]
    order_id = db.save_order(conn, customer.strip(), email, lines)
    EmailNotifier().send(email, "Order received", f"Thanks, {customer.strip()}.")
    return {"status": 201, "order_id": order_id}


def place_orders(requests):
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(
            pool.map(lambda r: INVENTORY.reserve(r["sku"], r["qty"]), requests)
        )


def get_invoice(request):
    if not check_api_key(request.get("api_key")):
        return {"status": 403}
    name = request.get("name")
    if not name:
        return {"status": 400, "error": "missing name"}
    try:
        data = files.read_invoice(name)
    except ValueError as exc:
        return {"status": 400, "error": str(exc)}
    except FileNotFoundError:
        return {"status": 404}
    return {"status": 200, "body": data}


def search_orders(conn, request):
    if not check_api_key(request.get("api_key")):
        return {"status": 403}
    return {"status": 200, "orders": orders.search(conn, request.get("q", ""))}


def list_orders(conn, request):
    if not check_api_key(request.get("api_key")):
        return {"status": 403}
    try:
        sort = request.get("sort")
        if sort:
            return {"status": 200, "orders": orders.sort_orders(conn, sort)}
        page = int(request.get("page", 1))
        return {"status": 200, "orders": orders.list_page(conn, page)}
    except ValueError as exc:
        return {"status": 400, "error": str(exc)}


def checkout_order(conn, request):
    try:
        result = checkout.checkout(
            conn, request.get("order_id"), request.get("actor"), request.get("coupon")
        )
    except checkout.CheckoutError as exc:
        return {"status": 400, "error": str(exc)}
    return {"status": 200, **result}


def create_coupon(conn, request):
    if not check_api_key(request.get("api_key")):
        return {"status": 403}
    expires_on = request.get("expires_on")
    try:
        if expires_on is not None:
            if not isinstance(expires_on, str):
                raise ValueError("expires_on must be an ISO date")
            expires_on = datetime.date.fromisoformat(expires_on)
        code = coupons.create_coupon(
            conn, request.get("actor"), request.get("code"), request.get("kind"),
            request.get("value"), request.get("min_total_cents", 0), expires_on,
            request.get("max_redemptions"),
        )
    except (coupons.CouponError, ValueError) as exc:
        return {"status": 400, "error": str(exc)}
    return {"status": 201, "code": code}
