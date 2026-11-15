"""Tests for timeparse/when.py: resolve_when, synonyms, formatter (plan §9)."""

import datetime as _dt
from zoneinfo import ZoneInfo

import pytest

from secretary.timeparse.format import format_when
from secretary.timeparse.when import (
    SYNONYMS,
    AmbiguousTime,
    PastTime,
    extract_when_phrase,
    normalize_text,
    parse_when,
    resolve_date,
    resolve_when,
    warm_up,
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


@pytest.mark.parametrize("text", ["11am", "at 11am", "11:00", "at 11:30 pm"])
def test_resolve_when_bare_clock_time_means_today_in_the_target_zone(text):
    # dateparser returns None for a bare clock time when RELATIVE_BASE is tz-aware and
    # TIMEZONE is set; the base must be passed as a naive local wall clock.
    dt = resolve_when(text, _now(), "Asia/Kolkata")
    assert dt.date() == _now().date()
    assert dt.tzinfo is not None
    assert (dt.hour, dt.minute) in {(11, 0), (23, 30), (11, 30)}


def test_resolve_when_bare_time_that_passed_means_the_next_occurrence():
    # Plan 9.2 ("at 9": next occurrence): 9am at 10:00 is tomorrow 9am, never a past time.
    dt = resolve_when("9am", _now(), "Asia/Kolkata")
    assert dt.date() == _now().date() + _dt.timedelta(days=1)
    assert (dt.hour, dt.minute) == (9, 0)


def test_resolve_when_bare_time_works_when_now_is_a_utc_instant():
    now_utc = _dt.datetime(2026, 11, 15, 15, 56, tzinfo=ZoneInfo("UTC"))  # 21:26 IST
    dt = resolve_when("at 11pm", now_utc, "Asia/Kolkata")
    assert (dt.day, dt.hour, dt.minute) == (15, 23, 0)
    dt = resolve_when("4pm", now_utc, "Asia/Kolkata")  # passed today: next occurrence
    assert (dt.day, dt.hour, dt.minute) == (16, 16, 0)
    with pytest.raises(PastTime):
        resolve_when("today 4pm", now_utc, "Asia/Kolkata")


def test_parse_when_allows_a_time_that_already_passed_today():
    now_utc = _dt.datetime(2026, 11, 15, 15, 56, tzinfo=ZoneInfo("UTC"))  # 21:26 IST
    dt = parse_when("today 4pm", now_utc, "Asia/Kolkata")
    assert (dt.day, dt.hour, dt.minute) == (15, 16, 0)
    assert dt.tzinfo is not None


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


def test_warm_up_runs_without_error():
    # dateparser warm-up on the worker thread must not raise.
    warm_up()


def test_extract_when_phrase_pulls_the_time_expression():
    assert extract_when_phrase("remind me to drink water in 10 minutes") == "in 10 minutes"
    assert extract_when_phrase("remind me to call mum tomorrow") == "tomorrow"
    assert extract_when_phrase("remind me to stretch") == "remind me to stretch"  # no phrase: unchanged


def test_resolve_when_reads_clock_times_in_the_target_zone_even_if_now_is_utc():
    """A UTC 'now' must not shift 'tomorrow at 9am' (regression: tools passed UTC)."""
    now_utc = _dt.datetime(2026, 11, 15, 4, 30, tzinfo=_dt.UTC)  # 10:00 in Kolkata
    for text, hour in (("tomorrow at 9am", 9), ("tomorrow at 5pm", 17)):
        got = resolve_when(text, now_utc, "Asia/Kolkata")
        assert (got.day, got.hour, got.minute) == (16, hour, 0)
        assert got.utcoffset() == _dt.timedelta(hours=5, minutes=30)


def test_resolve_when_same_instant_gives_same_answer_in_utc_or_local():
    local = _dt.datetime(2026, 11, 15, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    as_utc = local.astimezone(_dt.UTC)
    for text in ("tomorrow at 9am", "in 20 minutes", "friday at 3pm"):
        assert resolve_when(text, local, "Asia/Kolkata") == resolve_when(text, as_utc, "Asia/Kolkata")


def test_resolve_date_uses_the_target_zone_day():
    # 20:00 UTC on the 14th is already 01:30 on the 15th in Kolkata.
    now_utc = _dt.datetime(2026, 11, 14, 20, 0, tzinfo=_dt.UTC)
    assert resolve_date("today", now_utc, "Asia/Kolkata") == _dt.date(2026, 11, 15)
