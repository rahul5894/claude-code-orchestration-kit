"""Money helpers. Amounts are integer cents everywhere inside the service."""
import re

_AMOUNT = re.compile(r"(-?)([0-9]+)(?:\.([0-9]{1,2}))?")


def to_cents(amount: str | int) -> int:
    """Convert an amount in dollars to integer cents.

    `amount` is a str with at most two decimals, or an int: "19.99" -> 1999, "5" -> 500,
    "-3.10" -> -310, 7 -> 700. Anything else - more decimals, "nan", "inf", a float, a bool,
    None - raises ValueError.
    """
    if isinstance(amount, bool):
        raise ValueError(f"not an amount: {amount!r}")
    if isinstance(amount, int):
        return amount * 100
    m = _AMOUNT.fullmatch(amount.strip()) if isinstance(amount, str) else None
    if m is None:
        raise ValueError(f"not an amount: {amount!r}")
    sign, whole, frac = m.groups()
    cents = int(whole) * 100 + int((frac or "").ljust(2, "0"))
    return -cents if sign else cents


def format_cents(cents: int) -> str:
    """Format integer cents for display: 1999 -> "$19.99", 5 -> "$0.05", -150 -> "-$1.50",
    123456789 -> "$1,234,567.89"."""
    dollars, rest = divmod(abs(cents), 100)
    return f"{'-' if cents < 0 else ''}${dollars:,}.{rest:02d}"
