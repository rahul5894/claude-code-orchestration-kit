import calendar
import datetime
import re


def utc_today() -> datetime.date:
    """Today's date in UTC."""
    return datetime.datetime.now(datetime.UTC).date()


def add_months(d: datetime.date, n: int) -> datetime.date:
    """The date n months after d (n may be negative). A day that does not exist in the target
    month is clamped to that month's last day: Jan 31 + 1 month = Feb 28 (Feb 29 in a leap
    year)."""
    year, month0 = divmod(d.year * 12 + d.month - 1 + n, 12)
    month = month0 + 1
    return d.replace(year=year, month=month, day=min(d.day, calendar.monthrange(year, month)[1]))


def months_between(start: datetime.date, end: datetime.date) -> int:
    """Whole calendar months from start's month to end's month."""
    return (end.year - start.year) * 12 + end.month - start.month


def parse_date(text) -> datetime.date:
    """Parse an ISO date "YYYY-MM-DD". Raises ValueError for anything else."""
    if not isinstance(text, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
        raise ValueError(f"not an ISO date: {text!r}")
    return datetime.date.fromisoformat(text)
