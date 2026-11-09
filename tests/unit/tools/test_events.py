"""Tests for calendar event tools (plan §8.5, §13).

event_create is class B (own event, no attendees): it resolves the user's
``when_text`` in code and persists through ``events_repo``.
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import time_machine

from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import events as events_repo
from secretary.timeparse.when import PastTime
from secretary.tools.events import event_create, event_list


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "e.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


def _future_window(days: int = 7):
    now = datetime.now(UTC)
    return now.isoformat(), (now + timedelta(days=days)).isoformat()


def test_event_create_persists_in_store():
    conn = _conn()
    try:
        result = event_create(
            conn,
            "turn-1",
            {
                "title": "team standup",
                "when_text": "tomorrow 09:00",
                "duration_text": "30 minutes",
                "tz": "Asia/Kolkata",
            },
        )
        assert "event_id" in result
        assert result["title"] == "team standup"
        start, end = _future_window()
        rows = events_repo.list_window(conn, start_at=start, end_at=end)
        assert any(r["title"] == "team standup" for r in rows)
    finally:
        conn.close()


def test_event_create_past_time_raises():
    conn = _conn()
    try:
        with pytest.raises(PastTime):
            event_create(
                conn,
                "turn-1",
                {"title": "late meeting", "when_text": "yesterday 09:00", "tz": "Asia/Kolkata"},
            )
    finally:
        conn.close()


def test_event_list_returns_created_events():
    conn = _conn()
    try:
        event_create(
            conn, "turn-1", {"title": "standup", "when_text": "tomorrow 09:00", "tz": "Asia/Kolkata"}
        )
        event_create(
            conn, "turn-1", {"title": "review", "when_text": "tomorrow 14:00", "tz": "Asia/Kolkata"}
        )
        result = event_list(conn, "turn-1", {"filter": "week"})
        titles = {e["title"] for e in result["events"]}
        assert titles == {"standup", "review"}
    finally:
        conn.close()


def test_event_create_warns_on_overlapping_event():
    # Freeze now to 2026-11-09 04:00 UTC (09:30 Kolkata) so both "today" events
    # are future and overlap (10:00-11:00 vs 10:30-11:30 Kolkata).
    frozen = datetime(2026, 11, 9, 4, 0, 0, tzinfo=UTC)
    with time_machine.travel(frozen):
        conn = _conn()
        try:
            event_create(
                conn, "turn-1", {"title": "first event", "when_text": "today 10:00", "tz": "Asia/Kolkata"}
            )
            result = event_create(
                conn, "turn-2", {"title": "second event", "when_text": "today 10:30", "tz": "Asia/Kolkata"}
            )
            assert "event_id" in result
            assert "conflicts" in result
            assert any(c["title"] == "first event" for c in result["conflicts"])
        finally:
            conn.close()


def test_event_create_all_day_stores_day_bounds():
    # Kolkata 2026-11-09 all day -> stored as [2026-11-08 18:30Z, 2026-11-09 18:30Z).
    frozen = datetime(2026, 11, 9, 4, 0, 0, tzinfo=UTC)
    with time_machine.travel(frozen):
        conn = _conn()
        try:
            result = event_create(
                conn,
                "turn-1",
                {"title": "holiday", "when_text": "2026-11-09", "tz": "Asia/Kolkata", "all_day": True},
            )
            assert result["event_id"]
            assert result["all_day"] is True
            assert result["start_at"] == "2026-11-09T00:00:00+05:30"
            row = events_repo.list_window(
                conn, start_at="2026-11-08T18:30:00+00:00", end_at="2026-11-09T18:30:00+00:00"
            )[0]
            assert row["all_day"] == 1
            assert row["start_at"] == "2026-11-08T18:30:00+00:00"
            assert row["end_at"] == "2026-11-09T18:30:00+00:00"
        finally:
            conn.close()


def test_event_create_all_day_conflicts_with_timed_event():
    frozen = datetime(2026, 11, 9, 4, 0, 0, tzinfo=UTC)
    with time_machine.travel(frozen):
        conn = _conn()
        try:
            event_create(
                conn,
                "turn-1",
                {"title": "holiday", "when_text": "2026-11-09", "tz": "Asia/Kolkata", "all_day": True},
            )
            result = event_create(
                conn, "turn-2", {"title": "meeting", "when_text": "today 10:00", "tz": "Asia/Kolkata"}
            )
            assert any(c["title"] == "holiday" for c in result["conflicts"])
        finally:
            conn.close()
