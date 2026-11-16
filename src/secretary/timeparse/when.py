"""Time resolution: ``resolve_when`` turns a user's ``when_text`` into a datetime.

The LLM passes ``when_text`` verbatim; code resolves it (plan §9.1).
``dateparser`` is lazy-imported here so the worker thread pays the import cost
only when a time is actually parsed (plan §9.2 performance row).
"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import dateparser


class AmbiguousTime(Exception):
    """Raised when the time text cannot be parsed (plan §9.1)."""


class AmbiguousClock(AmbiguousTime):
    """A bare hour such as "at 5": morning or evening cannot be guessed (plan 9.2). Ask the user."""


class PastTime(Exception):
    """Raised when the resolved time is not strictly in the future (plan §9.1)."""


# Whole-phrase synonyms → dateparser-friendly "today at HH:MM" forms.
# dateparser parses "tonight" natively, but bare "EOD"/"20:00" do not parse,
# so we normalise whole-phrase synonyms for deterministic results (plan §9.2).
_WHOLE_PHRASE_SYNONYMS = {
    "tonight": "today at 20:00",
    "eod": "today at 20:00",
    "end of day": "today at 20:00",
    "this evening": "today at 18:00",
    "this afternoon": "today at 15:00",
    "this morning": "today at 09:00",
}

_DURATION_REPLACEMENTS = [
    ("half an hour", "30 minutes"),
    ("half hour", "30 minutes"),
]

# No TIMEZONE / RETURN_AS_TIMEZONE_AWARE here on purpose: with them dateparser treats a
# naive RELATIVE_BASE as UTC for clock-only text ("11am" rolled to tomorrow) and returns
# None for bare clock times when the base is aware. Everything runs on the target zone's
# naive wall clock instead, and the zone is attached afterwards.
_SETTINGS = {
    "DATE_ORDER": "DMY",  # plan §9.2: "05/11" → 5 November
    "PREFER_DATES_FROM": "future",
}


def normalize_text(text: str) -> str:
    """Pre-normalise whole-phrase synonyms and multi-word durations."""
    result = text.strip()
    low = result.lower()
    if low in _WHOLE_PHRASE_SYNONYMS:
        return _WHOLE_PHRASE_SYNONYMS[low]
    for old, new in _DURATION_REPLACEMENTS:
        result = result.replace(old, new)
    return result


SYNONYMS = _WHOLE_PHRASE_SYNONYMS  # public name (synonym → normalized phrase)


# "at 5" / "5": an hour with no minutes, no am/pm and no unit after it. dateparser reads such a
# number as a day of the month ("at 5" -> the 5th) or ignores it ("tomorrow at 8" -> now).
_AT_HOUR = re.compile(
    r"\bat\s+(\d{1,2})\b"
    r"(?!\s*(?::|\.\d|/|-|[ap]\.?m\b|h\b|hrs?\b|st\b|nd\b|rd\b|th\b"
    r"|min|hour|sec|day|week|month))",
    re.IGNORECASE,
)
_BARE_HOUR = re.compile(r"^\s*(\d{1,2})\s*$")
_EVENING = re.compile(r"\b(?:tonight|evening|night|afternoon)\b", re.IGNORECASE)
_MORNING = re.compile(r"\bmorning\b", re.IGNORECASE)


def _clarify_clock(text: str) -> str:
    """Make a bare hour explicit, or raise :class:`AmbiguousClock` when it cannot be known.

    A 24-hour hour (13-23, 0) is a clock time; a daypart word ("tonight at 9", "tomorrow
    morning at 8") decides am/pm; a plain 1-12 hour ("at 5") is ambiguous. Times with
    minutes ("8:30"), an am/pm, a date or a duration are left alone.
    """
    match = _AT_HOUR.search(text) or _BARE_HOUR.match(text)
    if match is None:
        return text
    hour = int(match.group(1))
    if hour > 23:
        return text  # not a clock time; the parser decides
    if hour == 0 or hour >= 13:
        return text[: match.start(1)] + f"{hour:02d}:00" + text[match.end(1) :]
    if _MORNING.search(text):
        suffix = "am"
    elif _EVENING.search(text) and hour != 12:
        suffix = "pm"
    else:
        raise AmbiguousClock(text)
    return text[: match.end(1)] + suffix + text[match.end(1) :]


def _parse(text: str, now: datetime, tz: str) -> datetime | None:
    # dateparser reads clock times ("9am") and day boundaries ("today") on the wall
    # clock of RELATIVE_BASE, so the base is the target zone's naive local time even
    # when the caller holds a UTC instant (see the note on _SETTINGS).
    if now.tzinfo is not None:
        now = now.astimezone(ZoneInfo(tz)).replace(tzinfo=None)
    settings = {**_SETTINGS, "RELATIVE_BASE": now}
    parsed: datetime | None = dateparser.parse(text, settings=settings)
    return parsed


def parse_when(text: str, now: datetime, tz: str) -> datetime:
    """Resolve ``text`` to a datetime in ``tz`` without requiring it to be in the future.

    Used where only the wall-clock time matters (the time of day of a recurring
    event). Raises ``AmbiguousTime`` if unparseable.
    """
    zone = ZoneInfo(tz)
    text = _clarify_clock(text)
    dt = _parse(text, now, tz)
    if dt is None:
        dt = _parse(normalize_text(text), now, tz)
    if dt is None:
        raise AmbiguousTime(text)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=zone)
    return dt.astimezone(zone)


def resolve_when(text: str, now: datetime, tz: str) -> datetime:
    """Resolve ``text`` relative to ``now`` in zone ``tz``.

    Returns a timezone-aware datetime in ``tz``. Raises ``AmbiguousTime`` if
    unparseable, ``PastTime`` if the result is not strictly after ``now``.
    ``RELATIVE_BASE`` is passed explicitly so tests can freeze time.
    """
    dt = parse_when(text, now, tz)
    if dt <= now:
        raise PastTime(text, dt)
    return dt


def resolve_date(text: str, now: datetime, tz: str):
    """Resolve ``text`` to a calendar date in zone ``tz``.

    Same parsing as :func:`resolve_when` but returns only the date and does not
    reject past dates (planning may target any day).
    """
    zone = ZoneInfo(tz)
    dt = _parse(text, now, tz)
    if dt is None:
        dt = _parse(normalize_text(text), now, tz)
    if dt is None:
        raise AmbiguousTime(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone)
    else:
        dt = dt.astimezone(zone)
    return dt.date()


_WHEN_PHRASES = (
    re.compile(r"in\s+\d+\s*(minutes?|hours?|days?|weeks?)", re.IGNORECASE),
    re.compile(r"today\s+at\s+\d+", re.IGNORECASE),
    re.compile(r"at\s+\d+", re.IGNORECASE),
    re.compile(r"tomorrow", re.IGNORECASE),
    re.compile(r"next\s+\w+", re.IGNORECASE),
    re.compile(r"\d+\s*(minutes?|hours?)", re.IGNORECASE),
)


def extract_when_phrase(text: str) -> str:
    """Return the time expression inside a sentence (``"in 10 minutes"`` from
    ``"remind me to drink water in 10 minutes"``), or ``text`` unchanged if
    none is found. Quick-add input is a whole sentence; the resolver wants
    only the time part."""
    for pattern in _WHEN_PHRASES:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return text


def warm_up() -> None:
    """Import and warm up dateparser on the worker thread (plan §9.2, C-24).

    dateparser is slow to import (hundreds of ms); pay that cost once on the
    worker thread at startup instead of on the first ``resolve_when`` call.
    """
    _ = dateparser.parse("now", settings={**_SETTINGS, "RELATIVE_BASE": datetime.now()})
