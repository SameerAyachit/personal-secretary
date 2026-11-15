"""Recurring calendar events (ADR-007).

A series is a rolling window of ordinary ``events`` rows that share a
``series_id``. Each row is pushed to Google Calendar through the existing
idempotent path, so the Calendar and Today views need no recurrence logic. The
scheduler tops the window up (``scheduler/series_job.py``) so the series never
runs dry. Occurrence times come from ``timeparse.recurrence`` (code, not the LLM).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from secretary.store.repos import events as events_repo
from secretary.timeparse.recurrence import RecurrenceRule, next_occurrence, parse_recurrence

HORIZON_DAYS = 30
MAX_OCCURRENCES = 60
_WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def build_rule(recurrence_text: str, base_local: datetime, tz: str) -> RecurrenceRule:
    """Parse ``recurrence_text``; the time of day is the one the user gave in ``when_text``."""
    rule = parse_recurrence(recurrence_text, tz)
    rule.time = base_local.strftime("%H:%M")
    if rule.freq == "weekly" and not rule.byweekday:
        rule.byweekday = [_WEEKDAYS[base_local.weekday()]]
    return rule


def first_occurrence(rule: RecurrenceRule, now: datetime) -> datetime:
    """The next occurrence strictly after ``now`` (today's if its time is still ahead)."""
    return next_occurrence(replace(rule, interval=1), now.astimezone(ZoneInfo(rule.tz)), rule.tz)


def occurrences_after(
    rule: RecurrenceRule, after: datetime, horizon_end: datetime, limit: int = MAX_OCCURRENCES
) -> list[datetime]:
    """Occurrences strictly after ``after`` up to ``horizon_end``, at most ``limit``."""
    out: list[datetime] = []
    current = after
    while len(out) < limit:
        current = next_occurrence(rule, current, rule.tz)
        if current > horizon_end:
            break
        out.append(current)
    return out


def insert_occurrences(
    con: sqlite3.Connection,
    *,
    title: str,
    starts: list[datetime],
    duration_minutes: int,
    tz: str,
    location: str | None,
    series_id: str,
    rule: RecurrenceRule,
    turn_id: str | None,
) -> list[int]:
    """Insert one pending event row per start time; returns the new ids."""
    meta = json.dumps({"rule": rule.to_json(), "duration_minutes": duration_minutes})
    ids: list[int] = []
    for start in starts:
        end = start + timedelta(minutes=duration_minutes)
        ids.append(
            events_repo.create(
                con,
                title=title,
                start_at=start.astimezone(UTC).isoformat(),
                end_at=end.astimezone(UTC).isoformat(),
                tz=tz,
                all_day=0,
                location=location,
                google_event_id=uuid.uuid4().hex,
                sync_state="pending",
                turn_id=turn_id,
                series_id=series_id,
                recurrence_json=meta,
            )
        )
    return ids


def new_series_id() -> str:
    return uuid.uuid4().hex
