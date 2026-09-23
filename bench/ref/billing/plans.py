PLANS: dict[str, dict[str, int]] = {
    "basic": {"monthly_cents": 900, "seats": 1},
    "team": {"monthly_cents": 2900, "seats": 5},
    "business": {"monthly_cents": 9900, "seats": 25},
}


def price_of(plan: str) -> int:
    """Monthly price in cents of a known plan. Unknown plan -> KeyError."""
    return PLANS[plan]["monthly_cents"]
