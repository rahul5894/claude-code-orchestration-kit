import datetime


def prorate(monthly_cents: int, period_start: datetime.date, period_end: datetime.date,
            from_day: datetime.date) -> int:
    """Price for the rest of a billing period.

    Returns monthly_cents * remaining_days / period_days, rounded down to whole cents.
    remaining_days runs from `from_day` (inclusive) to `period_end` (exclusive); period_days
    is the period's real length, period_end - period_start (28 to 31 days). `from_day` must
    lie inside the period (period_start <= from_day < period_end), otherwise ValueError.
    """
    if not period_start <= from_day < period_end:
        raise ValueError(f"{from_day} is outside the period {period_start} - {period_end}")
    return monthly_cents * (period_end - from_day).days // (period_end - period_start).days
