"""Tests for timeparse/recurrence.py: grammar parser + next-occurrence (plan §9.3-9.4)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis.strategies import datetimes

from secretary.timeparse.recurrence import (
    RecurrenceRule,
    UnparseableRecurrence,
    next_occurrence,
    parse_recurrence,
)

TZ = "Asia/Kolkata"


def _dt(y, mo, d, h, mi, tz=TZ):
    return datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(tz))


# ---- parse_recurrence ----

def test_parse_daily():
    rule = parse_recurrence("every day at 9pm", TZ)
    assert rule.freq == "daily"
    assert rule.interval == 1
    assert rule.time == "21:00"
    assert rule.tz == TZ


def test_parse_weekdays():
    rule = parse_recurrence("every weekday at 8:30", TZ)
    assert rule.freq == "weekdays"
    assert rule.time == "08:30"


def test_parse_weekly_monday():
    rule = parse_recurrence("every Monday at 9am", TZ)
    assert rule.freq == "weekly"
    assert rule.byweekday == ["MO"]
    assert rule.time == "09:00"


def test_parse_every_n_weeks():
    rule = parse_recurrence("every 2 weeks on Friday at 5pm", TZ)
    assert rule.freq == "weekly"
    assert rule.interval == 2
    assert rule.byweekday == ["FR"]
    assert rule.time == "17:00"


def test_parse_monthly_31st():
    rule = parse_recurrence("every month on the 31st at 9am", TZ)
    assert rule.freq == "monthly"
    assert rule.bymonthday == [31]
    assert rule.time == "09:00"


def test_parse_monthly_first():
    rule = parse_recurrence("the first of every month at 10am", TZ)
    assert rule.freq == "monthly"
    assert rule.bymonthday == [1]
    assert rule.time == "10:00"


def test_parse_yearly_leap():
    rule = parse_recurrence("every year on Feb 29 at 10am", TZ)
    assert rule.freq == "yearly"
    assert rule.bymonth == [2]
    assert rule.bymonthday == [29]
    assert rule.time == "10:00"


def test_parse_default_time():
    rule = parse_recurrence("every Monday", TZ)
    assert rule.freq == "weekly"
    assert rule.time == "09:00"


def test_parse_unparseable():
    with pytest.raises(UnparseableRecurrence):
        parse_recurrence("whenever I feel like it", TZ)


# ---- next_occurrence ----

def test_next_occurrence_daily_today():
    rule = parse_recurrence("every day at 9pm", TZ)
    after = _dt(2026, 11, 7, 10, 0)
    nxt = next_occurrence(rule, after, TZ)
    assert nxt == _dt(2026, 11, 7, 21, 0)


def test_next_occurrence_daily_tomorrow_if_past():
    rule = parse_recurrence("every day at 9am", TZ)
    after = _dt(2026, 11, 7, 10, 0)  # 9am today already passed
    nxt = next_occurrence(rule, after, TZ)
    assert nxt == _dt(2026, 11, 8, 9, 0)


def test_next_occurrence_weekdays_skips_weekend():
    rule = parse_recurrence("every weekday at 9am", TZ)
    # Saturday Nov 7 2026 -> next weekday is Monday Nov 9
    after = _dt(2026, 11, 7, 10, 0)  # Saturday
    nxt = next_occurrence(rule, after, TZ)
    assert nxt == _dt(2026, 11, 9, 9, 0)
    assert nxt.weekday() == 0  # Monday


def test_next_occurrence_weekly_monday():
    rule = parse_recurrence("every Monday at 8:30", TZ)
    after = _dt(2026, 11, 7, 10, 0)  # Saturday
    nxt = next_occurrence(rule, after, TZ)
    assert nxt == _dt(2026, 11, 9, 8, 30)  # Monday


def test_next_occurrence_monthly_31st_snaps_feb():
    # Jan 31 -> Feb 28 (last day of shorter month) -> Mar 31
    rule = parse_recurrence("every month on the 31st at 9am", TZ)
    after = _dt(2026, 1, 31, 10, 0)
    nxt = next_occurrence(rule, after, TZ)
    assert nxt == _dt(2026, 2, 28, 9, 0), nxt
    nxt2 = next_occurrence(rule, nxt, TZ)
    assert nxt2 == _dt(2026, 3, 31, 9, 0), nxt2


def test_next_occurrence_yearly_leap():
    rule = parse_recurrence("every year on Feb 29 at 10am", TZ)
    after = _dt(2024, 2, 29, 11, 0)  # just after 2024 Feb 29 10am
    nxt = next_occurrence(rule, after, TZ)
    # 2025 not a leap year -> snap to Feb 28
    assert nxt == _dt(2025, 2, 28, 10, 0), nxt


def test_next_occurrence_always_after():
    rule = parse_recurrence("every day at 9pm", TZ)
    after = _dt(2026, 11, 7, 10, 0)
    nxt = next_occurrence(rule, after, TZ)
    assert nxt > after


def test_next_occurrence_across_dst_london():
    # Europe/London: weekly Sunday at 2:30 across the March DST change.
    rule = parse_recurrence("every Sunday at 2:30", "Europe/London")
    # 2026-03-29 is the DST spring-forward Sunday in London
    after = datetime(2026, 3, 22, 12, 0, tzinfo=ZoneInfo("Europe/London"))
    nxt = next_occurrence(rule, after, "Europe/London")
    assert nxt == datetime(2026, 3, 29, 2, 30, tzinfo=ZoneInfo("Europe/London")), nxt


def test_next_occurrence_across_year_end():
    rule = parse_recurrence("every day at 11pm", TZ)
    after = _dt(2026, 12, 31, 10, 0)
    nxt = next_occurrence(rule, after, TZ)
    assert nxt == _dt(2026, 12, 31, 23, 0)
    nxt2 = next_occurrence(rule, nxt, TZ)
    assert nxt2 == _dt(2027, 1, 1, 23, 0), nxt2


# ---- property tests (hypothesis) ----

@given(st=datetimes(min_value=datetime(2026, 1, 1), max_value=datetime(2027, 1, 1)))
@settings(max_examples=40)
def test_next_occurrence_daily_always_after(st):
    after = st.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    rule = RecurrenceRule(freq="daily", interval=1, time="09:00", tz="Asia/Kolkata")
    nxt = next_occurrence(rule, after, "Asia/Kolkata")
    assert nxt > after
    assert nxt.hour == 9 and nxt.minute == 0


@given(st=datetimes(min_value=datetime(2026, 1, 1), max_value=datetime(2027, 1, 1)))
@settings(max_examples=40)
def test_next_occurrence_weekdays_is_weekday(st):
    after = st.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    rule = RecurrenceRule(freq="weekdays", interval=1, time="09:00", tz="Asia/Kolkata")
    nxt = next_occurrence(rule, after, "Asia/Kolkata")
    assert nxt > after
    assert nxt.weekday() < 5  # Mon-Fri
    assert nxt.hour == 9 and nxt.minute == 0
