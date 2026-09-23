from decimal import ROUND_HALF_UP, Decimal

RATES: dict[str, Decimal] = {
    "US-CA": Decimal("0.0725"),
    "US-NY": Decimal("0.08875"),
    "DE": Decimal("0.19"),
    "GB": Decimal("0.20"),
    "IN": Decimal("0.18"),
}


def tax_for(region: str, amount_cents: int) -> int:
    """Tax in whole cents on amount_cents for a region, rounded half up (14.5 -> 15).
    An amount of 0 or less has no tax. An unknown region raises ValueError."""
    try:
        rate = RATES[region]
    except (KeyError, TypeError):
        raise ValueError(f"unknown region: {region!r}") from None
    if amount_cents <= 0:
        return 0
    return int((amount_cents * rate).quantize(Decimal(1), rounding=ROUND_HALF_UP))
