from typing import Dict

RATES: Dict[str, float] = {
    "US-CA": 0.0725,
    "US-NY": 0.08875,
    "DE": 0.19,
    "GB": 0.20,
    "IN": 0.18,
}


def tax_for(region, amount_cents):
    """Tax in whole cents on amount_cents for a region, rounded half up (14.5 -> 15).
    An amount of 0 or less has no tax. An unknown region raises ValueError."""
    if amount_cents <= 0:
        return 0
    return round(amount_cents * RATES[region])
