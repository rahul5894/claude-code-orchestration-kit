from typing import Dict

PLANS: Dict[str, Dict[str, int]] = {
    "basic": dict(monthly_cents=900, seats=1),
    "team": dict(monthly_cents=2900, seats=5),
    "business": dict(monthly_cents=9900, seats=25),
}


def price_of(plan):
    """Monthly price in cents of a known plan. Unknown plan -> KeyError."""
    return PLANS[plan]["monthly_cents"]
