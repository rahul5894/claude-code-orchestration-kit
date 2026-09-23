import datetime

from billing import dates, invoices, plans
from billing.proration import prorate


class SubscriptionError(Exception):
    pass


def subscribe(conn, customer_id, plan, start):
    """Start a subscription on `start` (a date) and invoice its first month. Returns its id."""
    if plan not in plans.PLANS:
        raise SubscriptionError("unknown plan: %s" % plan)
    end = dates.add_months(start, 1)
    cur = conn.execute(
        "INSERT INTO subscriptions (customer_id, plan, started_on, period_start, period_end)"
        " VALUES (?, ?, ?, ?, ?)",
        (customer_id, plan, start.isoformat(), start.isoformat(), end.isoformat()),
    )
    conn.commit()
    subscription_id = cur.lastrowid
    invoices.issue_invoice(
        conn, customer_id, subscription_id,
        [("Plan %s %s to %s" % (plan, start, end), plans.price_of(plan))],
        issued_on=start,
    )
    return subscription_id


def get_subscription(conn, subscription_id):
    row = conn.execute(
        "SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)
    ).fetchone()
    return dict(row) if row else None


def cancel(conn, subscription_id):
    conn.execute(
        "UPDATE subscriptions SET status = 'cancelled' WHERE id = ?", (subscription_id,)
    )
    conn.commit()


def change_plan(conn, subscription_id, new_plan, actor, on):
    sub = get_subscription(conn, subscription_id)
    if sub is None:
        raise SubscriptionError("unknown subscription")
    email = conn.execute(
        "SELECT email FROM customers WHERE id = ?", (sub["customer_id"],)
    ).fetchone()["email"]
    if not (isinstance(actor, str) and (actor.startswith("staff:") or actor == email)):
        raise SubscriptionError("not allowed")
    if sub["status"] != "active" or new_plan not in plans.PLANS or new_plan == sub["plan"]:
        raise SubscriptionError("not allowed")
    start = datetime.date.fromisoformat(sub["period_start"])
    end = datetime.date.fromisoformat(sub["period_end"])
    if not start <= on < end:
        raise SubscriptionError("outside the period")
    credit = prorate(plans.price_of(sub["plan"]), start, end, on)
    charge = prorate(plans.price_of(new_plan), start, end, on)
    conn.execute("UPDATE subscriptions SET plan = ? WHERE id = ?", (new_plan, subscription_id))
    conn.commit()
    invoice_id, added = None, 0
    if charge > credit:
        invoice_id = invoices.issue_invoice(
            conn, sub["customer_id"], subscription_id,
            [("Unused time on %s" % sub["plan"], -credit),
             ("Remaining time on %s" % new_plan, charge)],
            issued_on=on,
        )
    else:
        added = credit - charge
        conn.execute("UPDATE customers SET credit_cents = credit_cents + ? WHERE id = ?",
                     (added, sub["customer_id"]))
        conn.commit()
    return {"subscription_id": subscription_id, "plan": new_plan, "invoice_id": invoice_id,
            "credit_added_cents": added}


def run_billing(conn, today):
    issued = []
    rows = conn.execute(
        "SELECT * FROM subscriptions WHERE status = 'active' AND period_end <= ? ORDER BY id",
        (today.isoformat(),),
    ).fetchall()
    for sub in rows:
        end = datetime.date.fromisoformat(sub["period_end"])
        while end <= today:
            start, end = end, dates.add_months(end, 1)
            price = plans.price_of(sub["plan"])
            credit = conn.execute(
                "SELECT credit_cents FROM customers WHERE id = ?", (sub["customer_id"],)
            ).fetchone()[0]
            lines = [("Plan %s %s to %s" % (sub["plan"], start, end), price)]
            used = min(credit, price)
            if used > 0:
                lines.append(("Credit applied", -used))
                conn.execute("UPDATE customers SET credit_cents = credit_cents - ? WHERE id = ?",
                             (used, sub["customer_id"]))
            issued.append(invoices.issue_invoice(conn, sub["customer_id"], sub["id"], lines,
                                                 issued_on=start))
        conn.execute("UPDATE subscriptions SET period_start = ?, period_end = ? WHERE id = ?",
                     (start.isoformat(), end.isoformat(), sub["id"]))
        conn.commit()
    return issued
