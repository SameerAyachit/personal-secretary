"""Tests for scheduler/ticker.py: atomic fire + per-tick jobs (plan §10.1-10.2)."""

import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from secretary.scheduler.ticker import _fire_due, now_utc, tick
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import reminders as reminders_repo


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "tick.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _past(now: datetime, minutes: int) -> str:
    return _utc_iso(now - timedelta(minutes=minutes))


def test_fire_due_creates_inbox_and_marks_done():
    conn = _conn()
    try:
        now = now_utc()
        rid = reminders_repo.create(
            conn,
            task_id=None,
            title="drink water",
            body="",
            kind="once",
            tz="Asia/Kolkata",
            rule_json=None,
            next_fire_at=_past(now, 5),
            turn_id=None,
        )
        created = conn.write(_fire_due)
        assert len(created) == 1
        assert created[0]["reminder_id"] == rid
        assert created[0]["title"] == "drink water"
        # reminder is now done.
        rem = reminders_repo.get(conn, rid)
        assert rem["status"] == "done"
        # a run was recorded.
        runs = conn.execute("SELECT * FROM reminder_runs WHERE reminder_id=?", (rid,)).fetchall()
        assert len(runs) == 1
        assert runs[0]["outcome"] == "fired"
        # inbox row exists.
        inbox = conn.execute("SELECT * FROM inbox WHERE reminder_id=?", (rid,)).fetchall()
        assert len(inbox) == 1
        assert inbox[0]["status"] == "unacknowledged"
    finally:
        conn.close()


def test_duplicate_fire_prevented():
    conn = _conn()
    try:
        now = now_utc()
        rid = reminders_repo.create(
            conn,
            task_id=None,
            title="dup",
            body="",
            kind="once",
            tz="Asia/Kolkata",
            rule_json=None,
            next_fire_at=_past(now, 5),
            turn_id=None,
        )
        conn.write(_fire_due)
        # Reset to scheduled with the SAME next_fire_at to test the unique run guard.
        conn.execute(
            "UPDATE reminders SET status='scheduled' WHERE id=?", (rid,)
        )
        created = conn.write(_fire_due)
        assert len(created) == 0  # duplicate run skipped via unique constraint
        runs = conn.execute("SELECT COUNT(*) AS n FROM reminder_runs WHERE reminder_id=?", (rid,)).fetchone()[0]
        assert runs == 1  # unique(reminder_id, scheduled_for) prevents a duplicate run
    finally:
        conn.close()


def test_recurring_advances_next_fire():
    conn = _conn()
    try:
        now = now_utc()
        rid = reminders_repo.create(
            conn,
            task_id=None,
            title="every day at 9am",
            body="",
            kind="recurring",
            tz="Asia/Kolkata",
            rule_json='{"freq":"daily","interval":1,"time":"09:00","tz":"Asia/Kolkata"}',
            next_fire_at=_past(now, 5),
            turn_id=None,
        )
        created = conn.write(_fire_due)
        assert len(created) == 1
        rem = reminders_repo.get(conn, rid)
        assert rem["status"] == "scheduled"
        assert rem["next_fire_at"] is not None
        # next fire is in the future.
        assert datetime.fromisoformat(rem["next_fire_at"].replace("Z", "+00:00")) > now
    finally:
        conn.close()


def test_tick_runs_without_error():
    conn = _conn()
    try:
        tick(conn)
    finally:
        conn.close()
