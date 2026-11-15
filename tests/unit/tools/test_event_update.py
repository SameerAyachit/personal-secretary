"""event_update: change an own event; Google gets the change via the pending push."""

from __future__ import annotations

import sqlite3
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import secretary.tools.events as events_tools
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import events as events_repo
from secretary.tools.events import event_update
from secretary.tools.registry import Registry, SafetyClass

TZ = "Asia/Kolkata"


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "e.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


@pytest.fixture(autouse=True)
def _now(monkeypatch):
    monkeypatch.setattr(events_tools, "_utc_now", lambda: datetime(2026, 11, 15, 4, 30, tzinfo=UTC))


def _event(conn, title="Dentist", *, start=None, etag=None, sync_state="synced", all_day=0):
    start = start or datetime(2026, 11, 20, 4, 30, tzinfo=UTC)
    return events_repo.create(
        conn, title=title, start_at=start.isoformat(),
        end_at=(start + timedelta(hours=1)).isoformat(), tz=TZ, all_day=all_day,
        google_event_id=uuid.uuid4().hex, etag=etag, sync_state=sync_state)


def test_registered_as_class_b_calendar_tool():
    registry = Registry()
    events_tools.register(registry)
    spec = registry.get("event_update")
    assert spec is not None and spec.safety_class == SafetyClass.B and spec.group == "calendar"


def test_reschedule_keeps_duration_and_marks_pending_push():
    conn = _conn()
    try:
        eid = _event(conn, etag='"e1"')
        out = event_update(conn, "t", {"event_ref": str(eid), "when_text": "tomorrow at 3pm", "tz": TZ})
        row = events_repo.get(conn, eid)
        assert row["start_at"].startswith("2026-11-16T09:30")  # 15:00 IST
        assert row["end_at"].startswith("2026-11-16T10:30")    # still one hour
        assert row["sync_state"] == "pending"
        assert out["event_id"] == eid
    finally:
        conn.close()


def test_title_location_and_duration_change():
    conn = _conn()
    try:
        eid = _event(conn)
        event_update(conn, "t", {"event_ref": "dentist", "title": "Dentist - cleaning",
                                 "location": "Clinic B", "duration_text": "30 minutes", "tz": TZ})
        row = events_repo.get(conn, eid)
        assert row["title"] == "Dentist - cleaning" and row["location"] == "Clinic B"
        start = datetime.fromisoformat(row["start_at"])
        assert datetime.fromisoformat(row["end_at"]) - start == timedelta(minutes=30)
    finally:
        conn.close()


def test_ambiguous_fragment_returns_candidates_and_changes_nothing():
    conn = _conn()
    try:
        _event(conn, "Team sync")
        _event(conn, "Team lunch")
        out = event_update(conn, "t", {"event_ref": "team", "title": "X", "tz": TZ})
        assert len(out["candidates"]) == 2
        assert {e["title"] for e in events_repo.list_window(
            conn, start_at="2026-11-01T00:00:00+00:00", end_at="2026-12-01T00:00:00+00:00")} == {"Team sync", "Team lunch"}
    finally:
        conn.close()


def test_errors_for_unknown_event_empty_change_and_bad_time():
    conn = _conn()
    try:
        eid = _event(conn)
        assert "error" in event_update(conn, "t", {"event_ref": "999", "title": "x", "tz": TZ})
        assert "error" in event_update(conn, "t", {"event_ref": str(eid), "tz": TZ})
        assert "error" in event_update(conn, "t", {"event_ref": str(eid), "when_text": "whenever the moon", "tz": TZ})
    finally:
        conn.close()


def test_all_day_event_moves_to_a_new_day():
    conn = _conn()
    try:
        start = datetime(2026, 11, 19, 18, 30, tzinfo=UTC)  # 20 Nov 00:00 IST
        eid = _event(conn, "Holiday", start=start, all_day=1)
        event_update(conn, "t", {"event_ref": str(eid), "when_text": "21 november", "tz": TZ})
        row = events_repo.get(conn, eid)
        assert row["start_at"].startswith("2026-11-20T18:30")
        assert row["all_day"] == 1
    finally:
        conn.close()
