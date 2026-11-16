"""Bare hours ("at 5") and dayparts ("tonight at 9") (live eval ambig-3).

Before: "at 5" was read as the 5th of the month (then rejected as a past time), "tomorrow at 8" became
tomorrow at the current time of day, and "tonight at 9" at 10:00 resolved to 09:00 (a past time).
Now a daypart decides AM/PM, a 24-hour hour is a clock time, and a bare 1-12 hour is ambiguous: ask.
"""

from __future__ import annotations

import datetime as _dt
from zoneinfo import ZoneInfo

import pytest

from secretary.timeparse.when import (
    AmbiguousClock,
    AmbiguousTime,
    extract_when_phrase,
    parse_when,
    resolve_when,
)
from secretary.tools.timeerrors import time_error

TZ = "Asia/Kolkata"
NOW = _dt.datetime(2026, 11, 16, 10, 0, tzinfo=ZoneInfo(TZ))


@pytest.mark.parametrize(
    "text,day_offset,hour",
    [
        ("tonight at 9", 0, 21),
        ("this evening at 7", 0, 19),
        ("this afternoon at 3", 0, 15),
        ("tomorrow evening at 7", 1, 19),
        ("tomorrow night at 10", 1, 22),
        ("tomorrow morning at 8", 1, 8),
        ("at 17", 0, 17),
        ("tomorrow at 18", 1, 18),
    ],
)
def test_dayparts_and_24_hour_hours_resolve_to_a_clock_time(text, day_offset, hour):
    dt = resolve_when(text, NOW, TZ)
    assert dt.date() == NOW.date() + _dt.timedelta(days=day_offset)
    assert (dt.hour, dt.minute) == (hour, 0)


@pytest.mark.parametrize("text", ["at 5", "5", "tomorrow at 8", "friday at 9", "at 12", "at 5 o'clock", "at 9 tomorrow"])
def test_a_bare_hour_without_am_pm_is_ambiguous_not_guessed(text):
    with pytest.raises(AmbiguousClock):
        resolve_when(text, NOW, TZ)
    with pytest.raises(AmbiguousTime):  # existing handlers (tools) keep working
        parse_when(text, NOW, TZ)


@pytest.mark.parametrize(
    "text",
    [
        "at 5pm", "at 5 pm", "5pm", "tomorrow at 8am", "05/11 at 9am", "at 8:30", "8:30", "at 17:00",
        "in 20 minutes", "in 5 minutes", "in 30 seconds", "in 2 hours", "in half an hour",
        "April 15", "15 April", "tonight", "EOD", "tomorrow", "friday 5pm", "the 1st",
    ],
)
def test_unambiguous_phrases_are_untouched(text):
    # Must not raise AmbiguousClock; some are in the past or unparseable for other reasons.
    try:
        parse_when(text, NOW, TZ)
    except AmbiguousClock:
        pytest.fail(f"{text!r} should not be treated as a bare hour")
    except AmbiguousTime:
        pass


def test_bare_hour_message_asks_am_or_pm():
    result = time_error(AmbiguousClock("at 5"), "at 5")
    assert "AM or PM" in result["error"] and "AM" in result["user_message"] and "PM" in result["user_message"]
    assert "at 5" in result["user_message"]


def test_extract_when_phrase_keeps_the_bare_hour_so_it_can_be_questioned():
    assert extract_when_phrase("remind me at 5") == "at 5"
