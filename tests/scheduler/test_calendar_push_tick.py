"""Scheduler: pushes pending events, throttles read sync, accepts clients late."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from secretary.scheduler.ticker import SchedulerThread, tick
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import events as events_repo
from secretary.store.repos import settings as settings_repo


class _FakeCalendar:
    def __init__(self) -> None:
        self.inserted: list[dict] = []
        self.listed = 0

    def insert_event(self, calendar_id: str, body: dict) -> dict:
        self.inserted.append(body)
        return {"id": body["id"], "etag": '"e"'}

    def list_events(self, *a, **k) -> dict:
        self.listed += 1
        return {"items": [], "nextSyncToken": "t"}


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "s.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


def _pending(conn) -> None:
    events_repo.create(
        conn, title="Dentist", start_at="2026-11-15T11:30:00+00:00",
        end_at="2026-11-15T12:30:00+00:00", tz="Asia/Kolkata",
        google_event_id="b" * 32, sync_state="pending",
    )


def test_tick_pushes_pending_and_notifies_calendar_changed():
    conn = _conn()
    _pending(conn)
    cal = _FakeCalendar()
    changed: list[int] = []
    tick(conn, calendar_client=cal, on_events_changed=lambda: changed.append(1))
    assert len(cal.inserted) == 1 and changed
    assert events_repo.list_pending(conn) == []


def test_read_sync_is_throttled_by_sync_minutes():
    conn = _conn()
    cal = _FakeCalendar()
    tick(conn, calendar_client=cal)
    tick(conn, calendar_client=cal)  # within google.sync_minutes: no second read
    assert cal.listed == 1
    settings_repo.set(conn, "google_last_sync", "2000-01-01T00:00:00Z")
    tick(conn, calendar_client=cal)
    assert cal.listed == 2


def test_scheduler_accepts_clients_after_start():
    sched = SchedulerThread(_conn())
    cal = _FakeCalendar()
    sched.set_google_clients(None, cal)
    assert sched._calendar_client is cal
