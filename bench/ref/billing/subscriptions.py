import datetime

from billing import customers, dates, db, invoices, plans
from billing.proration import prorate


class SubscriptionError(Exception):
    pass


class SubscriptionNotFound(SubscriptionError):
    pass


class NotAllowed(SubscriptionError):
    pass


def subscribe(conn, customer_id, plan, start):
    """Start a subscription on `start` (a date) and invoice its first month. Returns its id.

    A subscription's periods are whole months anchored on the day it started: one started on
    Jan 31 runs Jan 31 - Feb 28, Feb 28 - Mar 31, Mar 31 - Apr 30, ... (period_end is the first
    day of the next period)."""
    if plan not in plans.PLANS:
        raise SubscriptionError(f"unknown plan: {plan}")
    end = dates.add_months(start, 1)
    with db.transaction(conn):
        region = conn.execute(
            "SELECT region FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()["region"]
        subscription_id = conn.execute(
            "INSERT INTO subscriptions (customer_id, plan, started_on, period_start, period_end)"
            " VALUES (?, ?, ?, ?, ?)",
            (customer_id, plan, start.isoformat(), start.isoformat(), end.isoformat()),
        ).lastrowid
        invoices.insert_invoice(
            conn, invoices.next_id(conn), customer_id, subscription_id, region,
            [(f"Plan {plan} {start} to {end}", plans.price_of(plan))], start,
        )
    return subscription_id


def get_subscription(conn, subscription_id):
    row = conn.execute(
        "SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)
    ).fetchone()
    return dict(row) if row else None


def cancel(conn, subscription_id):
    """Cancel at once. No refund; a cancelled subscription is never billed again."""
    with conn:
        conn.execute(
            "UPDATE subscriptions SET status = 'cancelled' WHERE id = ?", (subscription_id,)
        )


def change_plan(conn, subscription_id, new_plan, actor, on):
    """Switch an active subscription to `new_plan` from `on` on; see bench/tickets/billing.txt."""
    if isinstance(subscription_id, bool) or not isinstance(subscription_id, int):
        raise SubscriptionError("subscription_id must be an int")
    if not isinstance(new_plan, str) or new_plan not in plans.PLANS:
        raise SubscriptionError(f"unknown plan: {new_plan!r}")
    if type(on) is not datetime.date:
        raise SubscriptionError("on must be a date")
    with db.transaction(conn):
        row = conn.execute(
            "SELECT s.customer_id, s.plan, s.status, s.period_start, s.period_end,"
            " c.email, c.region FROM subscriptions s JOIN customers c ON c.id = s.customer_id"
            " WHERE s.id = ?",
            (subscription_id,),
        ).fetchone()
        if row is None:
            raise SubscriptionNotFound(f"no subscription {subscription_id}")
        if not customers.may_act_for(actor, row["email"]):
            raise NotAllowed("not allowed to change this subscription")
        if row["status"] != "active":
            raise SubscriptionError("subscription is not active")
        if new_plan == row["plan"]:
            raise SubscriptionError(f"already on plan {new_plan}")
        start = datetime.date.fromisoformat(row["period_start"])
        end = datetime.date.fromisoformat(row["period_end"])
        if not start <= on < end:
            raise SubscriptionError("the change date is outside the current period")
        credit = prorate(plans.price_of(row["plan"]), start, end, on)
        charge = prorate(plans.price_of(new_plan), start, end, on)
        conn.execute("UPDATE subscriptions SET plan = ? WHERE id = ?", (new_plan, subscription_id))
        invoice_id, credit_added = None, 0
        if charge > credit:
            invoice_id = invoices.insert_invoice(
                conn, invoices.next_id(conn), row["customer_id"], subscription_id, row["region"],
                [(f"Unused time on {row['plan']}", -credit),
                 (f"Remaining time on {new_plan}", charge)],
                on,
            )
        else:
            credit_added = credit - charge
            conn.execute(
                "UPDATE customers SET credit_cents = credit_cents + ? WHERE id = ?",
                (credit_added, row["customer_id"]),
            )
    return {"subscription_id": subscription_id, "plan": new_plan, "invoice_id": invoice_id,
            "credit_added_cents": credit_added}


def run_billing(conn, today: datetime.date) -> list[int]:
    """Renew every due active subscription period by period up to `today`, one invoice per
    renewed period. Two SELECTs whatever the number of subscriptions; the whole run is one
    write transaction, so concurrent runs serialise and the later one finds nothing due."""
    issued = []
    with db.transaction(conn):
        due = conn.execute(
            "SELECT s.id, s.customer_id, s.plan, s.started_on, s.period_end,"
            " c.region, c.credit_cents FROM subscriptions s"
            " JOIN customers c ON c.id = s.customer_id"
            " WHERE s.status = 'active' AND s.period_end <= ? ORDER BY s.id",
            (today.isoformat(),),
        ).fetchall()
        if not due:
            return issued
        invoice_id = invoices.next_id(conn)
        credits = {}
        renewed = []
        for sub in due:
            started = datetime.date.fromisoformat(sub["started_on"])
            end = datetime.date.fromisoformat(sub["period_end"])
            credit = credits.get(sub["customer_id"], sub["credit_cents"])
            price = plans.price_of(sub["plan"])
            month = dates.months_between(started, end)
            while end <= today:
                start, month = end, month + 1
                end = dates.add_months(started, month)
                lines = [(f"Plan {sub['plan']} {start} to {end}", price)]
                if (used := min(credit, price)) > 0:
                    lines.append(("Credit applied", -used))
                    credit -= used
                issued.append(invoices.insert_invoice(
                    conn, invoice_id, sub["customer_id"], sub["id"], sub["region"], lines, start))
                invoice_id += 1
            credits[sub["customer_id"]] = credit
            renewed.append((start.isoformat(), end.isoformat(), sub["id"]))
        conn.executemany(
            "UPDATE subscriptions SET period_start = ?, period_end = ? WHERE id = ?", renewed)
        conn.executemany("UPDATE customers SET credit_cents = ? WHERE id = ?",
                         [(credit, customer_id) for customer_id, credit in credits.items()])
    return issued
