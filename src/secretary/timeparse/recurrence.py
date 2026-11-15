"""Recurrence grammar parser and next-occurrence computation (plan §9.3-9.4).

``recurrence_text`` is parsed by a small code grammar (regex + keyword table)
into a :class:`RecurrenceRule`. The next occurrence is computed with
``dateutil.rrule`` from the wall-clock time and stored tz, then converted to
UTC for ``next_fire_at``. Unparseable text raises :class:`UnparseableRecurrence`
(so the agent can ask the user to rephrase).

Month-end edge (plan §9.3): "every month on the 31st" fires on the last day of
shorter months (e.g. 31 January → 28 February → 31 March).
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_WEEKDAY_MAP = {
    "mo": 0, "monday": 0,
    "tu": 1, "tuesday": 1,
    "we": 2, "wednesday": 2,
    "th": 3, "thursday": 3,
    "fr": 4, "friday": 4,
    "sa": 5, "saturday": 5,
    "su": 6, "sunday": 6,
}
_INT_TO_WEEKDAY = {0: "MO", 1: "TU", 2: "WE", 3: "TH", 4: "FR", 5: "SA", 6: "SU"}

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_ORDINAL_MAP = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
                "fourth": 4, "4th": 4, "last": -1, "31st": 31}


class UnparseableRecurrence(Exception):
    """Raised when ``recurrence_text`` cannot be parsed (plan §9.3)."""


@dataclass
class RecurrenceRule:
    freq: str                      # daily|weekdays|weekly|monthly|yearly
    interval: int = 1
    byweekday: list[str] = field(default_factory=list)   # ["MO","TU",...]
    bymonthday: list[int] | None = None                  # day-of-month
    bymonth: list[int] | None = None                     # month-of-year
    time: str = "09:00"                                  # wall-clock HH:MM
    tz: str = "Asia/Kolkata"
    until: str | None = None
    count: int | None = None

    @classmethod
    def from_json(cls, data: dict) -> RecurrenceRule:
        """Rebuild a rule stored with :meth:`to_json`."""
        return cls(
            freq=data["freq"],
            interval=int(data.get("interval") or 1),
            byweekday=list(data.get("byweekday") or []),
            bymonthday=data.get("bymonthday"),
            bymonth=data.get("bymonth"),
            time=data.get("time") or "09:00",
            tz=data.get("tz") or "Asia/Kolkata",
            until=data.get("until"),
            count=data.get("count"),
        )

    def to_json(self) -> dict:
        return {
            "freq": self.freq,
            "interval": self.interval,
            "byweekday": self.byweekday,
            "bymonthday": self.bymonthday,
            "bymonth": self.bymonth,
            "time": self.time,
            "tz": self.tz,
            "until": self.until,
            "count": self.count,
        }


def _format_time(hour: int, minute: int, meridiem: str | None) -> str:
    h = hour
    if meridiem == "pm" and h < 12:
        h += 12
    if meridiem == "am" and h == 12:
        h = 0
    return f"{h:02d}:{minute:02d}"


def _parse_time(time_str: str) -> tuple[int, int]:
    h, m = time_str.split(":")
    return int(h), int(m)


def _days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _clamp_day(year: int, month: int, day: int) -> int:
    """Snap a day-of-month to the last day of shorter months (plan §9.3)."""
    return min(day, _days_in_month(year, month))


def parse_recurrence(text: str, default_tz: str) -> RecurrenceRule:
    """Parse ``recurrence_text`` into a :class:`RecurrenceRule`.

    Raises :class:`UnparseableRecurrence` if the text cannot be parsed.
    """
    t = text.strip()
    low = t.lower()

    # --- extract the wall-clock time ("at HH:MM" / "at 9pm") ---------------
    time_str = "09:00"
    m = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?(?:\s*(am|pm))?\b", low)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        time_str = _format_time(hour, minute, m.group(3))
        low = (low[: m.start()] + " " + low[m.end():]).strip()

    freq: str | None = None
    interval = 1
    byweekday: list[str] = []
    bymonthday: list[int] | None = None
    bymonth: list[int] | None = None

    # --- frequency / interval ---------------------------------------------
    m = re.search(
        r"\bevery\s+(?:(\d+)\s+)?(day|days|week|weeks|month|months|year|years|weekday|weekdays)\b",
        low,
    )
    if m:
        interval = int(m.group(1)) if m.group(1) else 1
        unit = m.group(2)
        if unit in ("day", "days"):
            freq = "daily"
        elif unit in ("week", "weeks"):
            freq = "weekly"
        elif unit in ("month", "months"):
            freq = "monthly"
        elif unit in ("year", "years"):
            freq = "yearly"
        elif unit in ("weekday", "weekdays"):
            freq = "weekdays"

    # --- "the first/31st of every month" ----------------------------------
    m = re.search(r"\bthe\s+(first|31st|1st|2nd|3rd)\s+of\s+every\s+month\b", low)
    if m:
        freq = "monthly"
        bymonthday = [_ORDINAL_MAP[m.group(1)]]

    # --- "on the 31st" / "on the first" -----------------------------------
    m = re.search(r"\bon\s+the\s+(first|31st|1st|2nd|3rd)\b", low)
    if m:
        freq = freq or "monthly"
        bymonthday = [_ORDINAL_MAP[m.group(1)]]

    # --- "on Feb 29" (yearly) ---------------------------------------------
    m = re.search(r"\bon\s+([a-z]{3,})\s+(\d{1,2})\b", low)
    if m:
        month = _MONTH_MAP.get(m.group(1)[:3])
        day = int(m.group(2))
        if month is not None:
            freq = freq or "yearly"
            bymonth = [month]
            bymonthday = [day]

    # --- "on Friday" / "every Monday" (weekly byweekday) ------------------
    m = re.search(
        r"\bon\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", low
    )
    if m:
        freq = freq or "weekly"
        byweekday = [_INT_TO_WEEKDAY[_WEEKDAY_MAP[m.group(1)[:2]]]]

    # bare "every Monday" without "on"
    if freq is None and byweekday == []:
        m = re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", low)
        if m:
            freq = "weekly"
            byweekday = [_INT_TO_WEEKDAY[_WEEKDAY_MAP[m.group(1)[:2]]]]

    if freq is None:
        raise UnparseableRecurrence(text)

    if freq == "monthly" and bymonthday is None:
        bymonthday = [1]

    return RecurrenceRule(
        freq=freq,
        interval=max(1, interval),
        byweekday=byweekday,
        bymonthday=bymonthday,
        bymonth=bymonth,
        time=time_str,
        tz=default_tz,
    )


def _next_single(rule: RecurrenceRule, after: datetime, tz: str) -> datetime:
    """Next occurrence for interval == 1 (strictly after ``after``)."""
    zone = ZoneInfo(tz)
    after_local = after.astimezone(zone)
    hour, minute = _parse_time(rule.time)

    if rule.freq == "daily":
        candidate = after_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= after_local:
            candidate += timedelta(days=1)
        return candidate

    if rule.freq == "weekdays":
        d = after_local.date()
        while True:
            candidate = datetime(d.year, d.month, d.day, hour, minute, tzinfo=zone)
            if d.weekday() < 5 and candidate > after_local:
                return candidate
            d += timedelta(days=1)

    if rule.freq == "weekly":
        targets = [_WEEKDAY_MAP[w.lower()[:2]] for w in rule.byweekday] or [0]
        d = after_local.date()
        while True:
            if d.weekday() in targets:
                candidate = datetime(d.year, d.month, d.day, hour, minute, tzinfo=zone)
                if candidate > after_local:
                    return candidate
            d += timedelta(days=1)

    if rule.freq in ("monthly", "yearly"):
        months = rule.bymonth or list(range(1, 13))
        days = rule.bymonthday or [1]
        d = after_local.date()
        # limit the search to avoid infinite loops
        for _ in range(24 * 12):
            if d.month in months:
                for raw_day in days:
                    day = _clamp_day(d.year, d.month, raw_day)
                    candidate = datetime(
                        d.year, d.month, day, hour, minute, tzinfo=zone
                    )
                    if candidate > after_local:
                        return candidate
            # advance to first day of next month
            if d.month == 12:
                d = datetime(d.year + 1, 1, 1, tzinfo=zone).date()
            else:
                d = datetime(d.year, d.month + 1, 1, tzinfo=zone).date()
        raise UnparseableRecurrence(f"no occurrence for {rule}")

    raise UnparseableRecurrence(f"unknown freq {rule.freq}")


def next_occurrence(rule: RecurrenceRule, after: datetime, tz: str) -> datetime:
    """Next occurrence of ``rule`` strictly after ``after`` (in ``tz``).

    Applies ``interval`` by advancing ``interval`` single steps.
    """
    current = after
    for _ in range(rule.interval):
        current = _next_single(rule, current, tz)
    return current
