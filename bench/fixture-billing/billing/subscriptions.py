from billing import dates, invoices, plans


class SubscriptionError(Exception):
    pass


def subscribe(conn, customer_id, plan, start):
    """Start a subscription on `start` (a date) and invoice its first month. Returns its id.

    A subscription's periods are whole months anchored on the day it started: one started on
    Jan 31 runs Jan 31 - Feb 28, Feb 28 - Mar 31, Mar 31 - Apr 30, ... (period_end is the first
    day of the next period)."""
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
    """Cancel at once. No refund; a cancelled subscription is never billed again."""
    conn.execute(
        "UPDATE subscriptions SET status = 'cancelled' WHERE id = ?", (subscription_id,)
    )
    conn.commit()
