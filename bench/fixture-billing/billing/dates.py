import datetime


def utc_today():
    """Today's date in UTC."""
    return datetime.datetime.utcnow().date()


def add_months(d, n):
    """The date n months after d (n may be negative). A day that does not exist in the target
    month is clamped to that month's last day: Jan 31 + 1 month = Feb 28 (Feb 29 in a leap
    year)."""
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    return d.replace(year=year, month=month)


def parse_date(text):
    """Parse an ISO date "YYYY-MM-DD". Raises ValueError for anything else."""
    return datetime.datetime.strptime(text, "%Y-%m-%d").date()
