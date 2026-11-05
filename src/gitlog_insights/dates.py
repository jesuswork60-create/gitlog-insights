"""Date handling: git's date spellings, filter bounds and calendar buckets."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterator

PERIODS = ("day", "week", "month", "year")

_RELATIVE = re.compile(r"^(\d+)([dwmy])$")
_RELATIVE_DAYS = {"d": 1, "w": 7, "m": 30, "y": 365}
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RAW = re.compile(r"^(\d+)(?: ([+-]\d{4}))?$")
_GIT_FORMATS = (
    "%a %b %d %H:%M:%S %Y %z",  # git's default format
    "%Y-%m-%d %H:%M:%S %z",  # --date=iso
    "%a, %d %b %Y %H:%M:%S %z",  # --date=rfc
)


def parse_git_date(text: str) -> datetime:
    """Parse any date form ``git log`` commonly prints; the result is always aware."""
    text = text.strip()
    raw = _RAW.match(text)
    if raw:
        seconds, offset = raw.groups()
        tz = timezone.utc
        if offset:
            tz = datetime.strptime(offset, "%z").tzinfo or timezone.utc
        return datetime.fromtimestamp(int(seconds), tz)
    for fmt in _GIT_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_bound(text: str, *, end: bool = False, now: datetime | None = None) -> datetime:
    """Parse a ``--since``/``--until`` value.

    Accepts an ISO date or datetime, or a relative age such as ``30d``, ``2w``,
    ``6m`` or ``1y`` counted back from ``now``. A bare date used as an end bound
    covers that whole day. Raises ``ValueError`` on anything else.
    """
    text = text.strip()
    relative = _RELATIVE.match(text)
    if relative:
        amount, unit = relative.groups()
        reference = now or datetime.now(timezone.utc)
        return reference - timedelta(days=int(amount) * _RELATIVE_DAYS[unit])
    if _DATE_ONLY.match(text):
        day = date.fromisoformat(text)
        clock = time.max if end else time.min
        return datetime.combine(day, clock, tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def bucket_key(moment: datetime, period: str) -> str:
    """Name the calendar bucket holding ``moment``, measured in UTC."""
    utc = moment.astimezone(timezone.utc)
    if period == "day":
        return utc.strftime("%Y-%m-%d")
    if period == "week":
        year, week, _ = utc.isocalendar()
        return f"{year}-W{week:02d}"
    if period == "month":
        return utc.strftime("%Y-%m")
    if period == "year":
        return utc.strftime("%Y")
    raise ValueError(f"unknown period {period!r}; expected one of {', '.join(PERIODS)}")


def iter_bucket_keys(first: datetime, last: datetime, period: str) -> Iterator[str]:
    """Yield every bucket key from ``first`` to ``last`` inclusive, gaps included."""
    start = first.astimezone(timezone.utc).date()
    stop = last.astimezone(timezone.utc).date()
    if period == "day":
        cursor = start
        step = timedelta(days=1)
    elif period == "week":
        cursor = start - timedelta(days=start.weekday())
        step = timedelta(days=7)
    elif period == "month":
        year, month = start.year, start.month
        while (year, month) <= (stop.year, stop.month):
            yield f"{year}-{month:02d}"
            month += 1
            if month == 13:
                year, month = year + 1, 1
        return
    elif period == "year":
        for year in range(start.year, stop.year + 1):
            yield f"{year}"
        return
    else:
        raise ValueError(f"unknown period {period!r}; expected one of {', '.join(PERIODS)}")
    while cursor <= stop:
        yield bucket_key(datetime.combine(cursor, time.min, tzinfo=timezone.utc), period)
        cursor += step
