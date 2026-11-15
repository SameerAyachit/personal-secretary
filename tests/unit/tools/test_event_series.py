"""Recurring events: a rolling window of ordinary event rows, topped up by the scheduler."""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import secretary.tools.events as events_tools
from secretary.scheduler import ticker
from secretary.scheduler.series_job import extend_series
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import events as events_repo
from secretary.store.repos import undo as undo_repo
from secretary.tools.events import event_create

TZ = "Asia/Kolkata"
IST = ZoneInfo(TZ)
NOW = datetime(2026, 11, 15, 15, 56, tzinfo=UTC)  # 21:26 IST, Sunday


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "s.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(events_tools, "_utc_now", lambda: NOW)


def _rows(conn, series_id=None):
    sql = "SELECT * FROM events WHERE deleted_at IS NULL"
    params: tuple = ()
    if series_id:
        sql += " AND series_id=?"
        params = (series_id,)
    cur = conn.execute(sql + " ORDER BY start_at", params)
    return [dict(r) for r in cur.fetchall()]


def _local(row) -> datetime:
    return datetime.fromisoformat(row["start_at"]).astimezone(IST)


def _make(conn, **extra):
    args = {"title": "Focus on course", "when_text": "4pm", "duration_text": "2 hours",
            "recurrence_text": "every day", "tz": TZ, **extra}
    return event_create(conn, "turn-1", args)


def test_daily_series_starts_tomorrow_because_today_4pm_has_passed():
    conn = _conn()
    try:
        out = _make(conn)
        assert "error" not in out, out
        rows = _rows(conn)
        first, last = _local(rows[0]), _local(rows[-1])
        assert (first.day, first.hour, first.minute) == (16, 16, 0)
        end = datetime.fromisoformat(rows[0]["end_at"]).astimezone(IST)
        assert (end.hour, end.minute) == (18, 0)
        assert out["count"] == len(rows) >= 29
        assert last <= NOW.astimezone(IST) + timedelta(days=30)
        days = [_local(r).date() for r in rows]
        assert days == [days[0] + timedelta(days=i) for i in range(len(days))]
        assert len({r["series_id"] for r in rows}) == 1 and rows[0]["series_id"]
        assert len({r["google_event_id"] for r in rows}) == len(rows)
        assert {r["sync_state"] for r in rows} == {"pending"}
    finally:
        conn.close()


def test_series_starts_today_when_the_time_is_still_ahead():
    conn = _conn()
    try:
        _make(conn, when_text="11pm", duration_text="1 hour")
        first = _local(_rows(conn)[0])
        assert (first.day, first.hour) == (15, 23)
    finally:
        conn.close()


def test_weekday_series_skips_weekends():
    conn = _conn()
    try:
        _make(conn, recurrence_text="every weekday")
        assert all(_local(r).weekday() < 5 for r in _rows(conn))
    finally:
        conn.close()


def test_weekly_series_without_a_day_uses_the_weekday_of_the_first_event():
    conn = _conn()
    try:
        _make(conn, when_text="tomorrow 4pm", recurrence_text="every week")
        rows = _rows(conn)
        assert {_local(r).weekday() for r in rows} == {0}  # tomorrow is Monday
        assert 4 <= len(rows) <= 5
    finally:
        conn.close()


def test_time_of_day_comes_from_when_text_not_the_default_rule_time():
    conn = _conn()
    try:
        _make(conn, recurrence_text="every day at 9am")
        assert _local(_rows(conn)[0]).hour == 16
    finally:
        conn.close()


def test_unparseable_recurrence_is_a_plain_error_and_creates_nothing():
    conn = _conn()
    try:
        out = _make(conn, recurrence_text="whenever")
        assert "user_message" in out and "repeat" in out["user_message"].lower()
        assert _rows(conn) == []
    finally:
        conn.close()


def test_recurring_all_day_events_are_refused_honestly():
    conn = _conn()
    try:
        out = _make(conn, all_day=True, when_text="tomorrow")
        assert "error" in out and "all-day" in out["error"].lower()
        assert _rows(conn) == []
    finally:
        conn.close()


def test_plain_event_is_unaffected():
    conn = _conn()
    try:
        out = event_create(conn, "t", {"title": "Dentist", "when_text": "tomorrow 3pm", "tz": TZ})
        assert "series_id" not in out and len(_rows(conn)) == 1
        assert _rows(conn)[0]["series_id"] is None
    finally:
        conn.close()


def test_undo_removes_every_unsynced_occurrence_in_the_series():
    conn = _conn()
    try:
        _make(conn)
        entry = undo_repo.list_for_turn(conn, "turn-1")[0]
        done, message = undo_repo.apply(conn, entry["id"])
        assert done and _rows(conn) == []
        assert "Undone" in message or "removed" in message.lower()
    finally:
        conn.close()


def test_undo_keeps_occurrences_already_on_google_and_says_so():
    conn = _conn()
    try:
        _make(conn)
        first = _rows(conn)[0]
        events_repo.set_sync_state(conn, first["id"], "synced")
        entry = undo_repo.list_for_turn(conn, "turn-1")[0]
        done, message = undo_repo.apply(conn, entry["id"])
        assert done
        assert [r["id"] for r in _rows(conn)] == [first["id"]]
        assert "Google" in message
    finally:
        conn.close()


def test_top_up_extends_the_window_without_duplicates():
    conn = _conn()
    try:
        _make(conn)
        before = _rows(conn)
        later = NOW + timedelta(days=20)
        added = extend_series(conn, now=later)
        after = _rows(conn)
        assert added == len(after) - len(before) > 0
        days = [_local(r).date() for r in after]
        assert days == [days[0] + timedelta(days=i) for i in range(len(days))]  # no gaps, no dupes
        assert extend_series(conn, now=later) == 0  # idempotent
    finally:
        conn.close()


def test_top_up_does_nothing_for_a_series_the_user_removed():
    conn = _conn()
    try:
        _make(conn)
        entry = undo_repo.list_for_turn(conn, "turn-1")[0]
        undo_repo.apply(conn, entry["id"])
        assert extend_series(conn, now=NOW + timedelta(days=20)) == 0
        assert _rows(conn) == []
    finally:
        conn.close()


def test_top_up_does_not_regenerate_a_deleted_last_occurrence():
    conn = _conn()
    try:
        _make(conn)
        last = _rows(conn)[-1]
        conn.execute("UPDATE events SET deleted_at='2026-11-16T00:00:00Z' WHERE id=?", (last["id"],))
        extend_series(conn, now=NOW + timedelta(days=1))
        assert last["start_at"] not in {r["start_at"] for r in _rows(conn)}
    finally:
        conn.close()


def test_tick_step_tops_up_and_notifies(monkeypatch):
    conn = _conn()
    try:
        _make(conn)
        calls = []
        monkeypatch.setattr(ticker, "extend_series", lambda c: 3)
        ticker._series_step(conn, lambda: calls.append(1))
        assert calls == [1]
        monkeypatch.setattr(ticker, "extend_series", lambda c: (_ for _ in ()).throw(RuntimeError("x")))
        ticker._series_step(conn, lambda: calls.append(2))  # logged, not raised
        assert calls == [1]
    finally:
        conn.close()
