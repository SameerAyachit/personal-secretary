"""Tests for scheduler/catchup.py: catch-up groups missed reminders (plan §10.4)."""

import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from secretary.scheduler.catchup import catch_up
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "catchup.db"
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


def test_catch_up_groups_many_missed_into_one_entry():
    conn = _conn()
    try:
        now = datetime.now(UTC)
        # 20 reminders all due in the past.
        ids = []
        for i in range(20):
            rid = reminders_repo_create(
                conn,
                title=f"reminder {i}",
                kind="once",
                next_fire_at=_past(now, 5),
            )
            ids.append(rid)
        result = catch_up(conn)
        assert result["count"] == 20
        assert len(result["titles"]) == 20
        # Exactly ONE inbox entry of kind while_away.
        rows = conn.execute(
            "SELECT * FROM inbox WHERE kind='while_away'"
        ).fetchall()
        assert len(rows) == 1
        assert "20 reminder(s) while you were away" in rows[0]["body"]
        # All 20 once-reminders are done.
        for rid in ids:
            rem = conn.execute("SELECT status FROM reminders WHERE id=?", (rid,)).fetchone()
            assert rem[0] == "done"
    finally:
        conn.close()


def test_catch_up_recurring_advances_to_future():
    conn = _conn()
    try:
        now = datetime.now(UTC)
        rid = reminders_repo_create(
            conn,
            title="daily 9am",
            kind="recurring",
            tz="Asia/Kolkata",
            rule_json='{"freq":"daily","interval":1,"time":"09:00","tz":"Asia/Kolkata"}',
            next_fire_at=_past(now, 5),
        )
        result = catch_up(conn)
        assert result["count"] == 1
        rem = conn.execute("SELECT * FROM reminders WHERE id=?", (rid,)).fetchone()
        assert rem["status"] == "scheduled"
        nxt = datetime.fromisoformat(rem["next_fire_at"].replace("Z", "+00:00"))
        assert nxt > now  # advanced to a future occurrence
    finally:
        conn.close()


def test_catch_up_no_due_reminders():
    conn = _conn()
    try:
        result = catch_up(conn)
        assert result["count"] == 0
        assert result["titles"] == []
        rows = conn.execute("SELECT * FROM inbox WHERE kind='while_away'").fetchall()
        assert len(rows) == 0
    finally:
        conn.close()


# Helpers ---------------------------------------------------------------

def reminders_repo_create(conn, title, kind, tz="Asia/Kolkata", rule_json=None, next_fire_at=None):
    conn.execute(
        "INSERT INTO reminders(task_id, title, body, kind, tz, rule_json, next_fire_at, "
        "status, priority, idempotency_key, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,'scheduled',0,?,?,?)",
        (None, title, "", kind, tz, rule_json, next_fire_at, f"ik-{next_fire_at}-{title}", _utc_iso(datetime.now(UTC)), _utc_iso(datetime.now(UTC))),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
