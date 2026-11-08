"""Tests for timeparse/when.py: resolve_when, synonyms, formatter (plan §9)."""

import datetime as _dt
from zoneinfo import ZoneInfo

import pytest

from secretary.timeparse.format import format_when
from secretary.timeparse.when import (
    SYNONYMS,
    AmbiguousTime,
    PastTime,
    normalize_text,
    resolve_when,
)


def _now(tz_name="Asia/Kolkata"):
    return _dt.datetime(2026, 11, 7, 10, 0, 0, tzinfo=ZoneInfo(tz_name))


@pytest.mark.parametrize("text,expected_hour", [
    ("in 20 minutes", 10),
    ("in half an hour", 10),
    ("tonight", 20),
    ("EOD", 20),
    ("tomorrow at 9am", 9),
])
def test_resolve_when_relative_and_synonyms(text, expected_hour):
    dt = resolve_when(text, _now(), "Asia/Kolkata")
    assert dt is not None
    assert dt.hour == expected_hour
    assert dt > _now()


def test_resolve_when_day_first():
    # 05/11 with DATE_ORDER=DMY → 5 November, not May 11.
    dt = resolve_when("05/11 at 9am", _now(), "Asia/Kolkata")
    assert dt.month == 11
    assert dt.day == 5
    assert dt.hour == 9


def test_resolve_when_past_time_raises():
    # "yesterday" resolves to a time in the past relative to 10am now.
    with pytest.raises(PastTime):
        resolve_when("yesterday", _now(), "Asia/Kolkata")


def test_resolve_when_unparseable_raises():
    with pytest.raises(AmbiguousTime):
        resolve_when("the thing", _now(), "Asia/Kolkata")


def test_resolve_when_bare_time_is_ambiguous():
    # A bare time like "9am" with no date/meridiem context does not parse.
    with pytest.raises(AmbiguousTime):
        resolve_when("9am", _now(), "Asia/Kolkata")


def test_resolve_when_returns_tz_aware():
    dt = resolve_when("tomorrow at 8am", _now(), "Asia/Kolkata")
    assert dt.tzinfo is not None


def test_normalize_text_whole_phrase_synonyms():
    assert normalize_text("tonight") == "today at 20:00"
    assert normalize_text("EOD") == "today at 20:00"
    assert normalize_text("this evening") == "today at 18:00"


def test_normalize_text_duration():
    assert normalize_text("in half an hour") == "in 30 minutes"
    # Non-synonym text is unchanged apart from duration replacement.
    assert normalize_text("tomorrow morning") == "tomorrow morning"


def test_synonyms_mapping():
    assert SYNONYMS["tonight"] == "today at 20:00"
    assert SYNONYMS["eod"] == "today at 20:00"


def test_format_when():
    dt = _dt.datetime(2026, 11, 7, 20, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    s = format_when(dt, "Asia/Kolkata")
    assert "2026" in s and "Nov" in s and "20:00" in s
