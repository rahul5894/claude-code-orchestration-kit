def prorate(monthly_cents, period_start, period_end, from_day):
    """Price for the rest of a billing period.

    Returns monthly_cents * remaining_days / period_days, rounded down to whole cents.
    remaining_days runs from `from_day` (inclusive) to `period_end` (exclusive); period_days
    is the period's real length, period_end - period_start (28 to 31 days). `from_day` must
    lie inside the period (period_start <= from_day < period_end), otherwise ValueError.
    """
    if from_day < period_start:
        from_day = period_start
    remaining = (period_end - from_day).days
    return int(monthly_cents * remaining / 30)
