"""Shared step after a reminder fires: advance a recurring series or finish it."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from secretary.store.repos import reminders as reminders_repo
from secretary.timeparse.recurrence import RecurrenceRule, next_occurrence


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_recurring(rem: dict) -> bool:
    return rem["kind"] == "recurring" and bool(rem["rule_json"])


def advance(con: sqlite3.Connection, rem: dict, now: datetime) -> None:
    """Reschedule a recurring reminder to its next future occurrence, or mark a
    one-off reminder done. Call after the run has been recorded."""
    now_iso = utc_iso(now)
    if is_recurring(rem):
        rule = RecurrenceRule(**json.loads(rem["rule_json"]))
        after_local = now.astimezone(ZoneInfo(rem["tz"]))
        nxt = next_occurrence(rule, after_local, rem["tz"])
        reminders_repo.reschedule(con, rem["id"], utc_iso(nxt), now_iso)
    else:
        reminders_repo.mark_done(con, rem["id"], now_iso)
