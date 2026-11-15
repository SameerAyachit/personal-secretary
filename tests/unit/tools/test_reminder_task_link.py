"""reminder_create can be tied to an existing task (task_ref)."""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

import secretary.tools.reminders as reminders_tools
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import reminders as reminders_repo
from secretary.store.repos import tasks as tasks_repo
from secretary.tools.reminders import reminder_create

TZ = "Asia/Kolkata"


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "r.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(reminders_tools, "_utc_now", lambda: datetime(2026, 11, 15, 4, 30, tzinfo=UTC))


def test_reminder_is_linked_to_the_task_by_id_or_title():
    conn = _conn()
    try:
        tid = tasks_repo.create(conn, title="Submit the lab report", source="user")
        out = reminder_create(conn, "t1", {"title": "lab report", "when_text": "tomorrow at 9am",
                                           "task_ref": str(tid), "tz": TZ})
        assert reminders_repo.get(conn, out["reminder_id"])["task_id"] == tid
        out = reminder_create(conn, "t2", {"title": "lab report 2", "when_text": "tomorrow at 10am",
                                           "task_ref": "lab report", "tz": TZ})
        assert reminders_repo.get(conn, out["reminder_id"])["task_id"] == tid
    finally:
        conn.close()


def test_unknown_or_ambiguous_task_creates_no_reminder():
    conn = _conn()
    try:
        tasks_repo.create(conn, title="Buy milk", source="user")
        tasks_repo.create(conn, title="Buy bread", source="user")
        out = reminder_create(conn, "t", {"title": "x", "when_text": "tomorrow at 9am",
                                          "task_ref": "buy", "tz": TZ})
        assert len(out["candidates"]) == 2
        out = reminder_create(conn, "t", {"title": "x", "when_text": "tomorrow at 9am",
                                          "task_ref": "nothing like it", "tz": TZ})
        assert "error" in out
        assert conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0
    finally:
        conn.close()


def test_reminder_without_task_ref_is_unlinked():
    conn = _conn()
    try:
        out = reminder_create(conn, "t", {"title": "stretch", "when_text": "tomorrow at 9am", "tz": TZ})
        assert reminders_repo.get(conn, out["reminder_id"])["task_id"] is None
    finally:
        conn.close()
