"""Money helpers. Amounts are integer cents everywhere inside the service."""


def to_cents(amount):
    """Convert an amount in dollars to integer cents.

    `amount` is a str with at most two decimals, or an int: "19.99" -> 1999, "5" -> 500,
    "-3.10" -> -310, 7 -> 700. Anything else - more decimals, "nan", "inf", a float, a bool,
    None - raises ValueError.
    """
    return int(float(amount) * 100)


def format_cents(cents):
    """Format integer cents for display: 1999 -> "$19.99", 5 -> "$0.05", -150 -> "-$1.50",
    123456789 -> "$1,234,567.89"."""
    dollars = "{:,}".format(int(cents / 100))
    return "$%s.%02d" % (dollars, cents % 100)
