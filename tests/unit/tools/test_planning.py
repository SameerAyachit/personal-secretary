"""Tests for the plan_day planning tool (plan §13 / §8.5)."""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import events as events_repo
from secretary.tools.planning import plan_day


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "p.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


def _add_event(conn, title, start_utc_iso, end_utc_iso, tz="Asia/Kolkata"):
    return events_repo.create(
        conn,
        title=title,
        start_at=start_utc_iso,
        end_at=end_utc_iso,
        tz=tz,
        turn_id="turn-test",
    )


def test_plan_day_returns_free_gaps():
    """Kolkata (UTC+5:30), Monday 2026-11-09, working 09:00-17:00 local.

    Busy: meeting 10:00-11:00 (04:30-05:30 UTC) and lunch 13:00-14:00
    (07:30-08:30 UTC). Expect free 09:00-10:00, 11:00-13:00, 14:00-17:00.
    """
    conn = _conn()
    try:
        _add_event(conn, "meeting", "2026-11-09T04:30:00+00:00", "2026-11-09T05:30:00+00:00")
        _add_event(conn, "lunch", "2026-11-09T07:30:00+00:00", "2026-11-09T08:30:00+00:00")
        result = plan_day(conn, "turn-1", {"date_text": "2026-11-09", "tz": "Asia/Kolkata"})
        assert result["date"] == "2026-11-09"
        assert result["tz"] == "Asia/Kolkata"
        assert result["free_slots"] == [
            {"start": "2026-11-09T09:00:00+05:30", "end": "2026-11-09T10:00:00+05:30"},
            {"start": "2026-11-09T11:00:00+05:30", "end": "2026-11-09T13:00:00+05:30"},
            {"start": "2026-11-09T14:00:00+05:30", "end": "2026-11-09T17:00:00+05:30"},
        ]
    finally:
        conn.close()


def test_plan_day_no_events_returns_full_working_day():
    conn = _conn()
    try:
        result = plan_day(conn, "turn-1", {"date_text": "2026-11-09", "tz": "Asia/Kolkata"})
        assert result["free_slots"] == [
            {"start": "2026-11-09T09:00:00+05:30", "end": "2026-11-09T17:00:00+05:30"},
        ]
    finally:
        conn.close()


def test_plan_day_all_day_event_blocks_whole_day():
    conn = _conn()
    try:
        events_repo.create(
            conn,
            title="holiday",
            start_at="2026-11-08T18:30:00+00:00",
            end_at="2026-11-09T18:30:00+00:00",
            tz="Asia/Kolkata",
            all_day=1,
            turn_id="turn-test",
        )
        result = plan_day(conn, "turn-1", {"date_text": "2026-11-09", "tz": "Asia/Kolkata"})
        assert result["free_slots"] == []
    finally:
        conn.close()


def test_plan_day_defaults_to_today():
    conn = _conn()
    try:
        result = plan_day(conn, "turn-1", {})
        today = datetime.now(UTC).astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
        assert result["date"] == today
        assert isinstance(result["free_slots"], list)
    finally:
        conn.close()
