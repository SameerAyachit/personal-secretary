"""Time problems come back from tools as plain, actionable errors (not raw exception reprs)."""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

import secretary.tools.events as events_tools
import secretary.tools.reminders as reminders_tools
import secretary.tools.tasks as tasks_tools
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate

TZ = "Asia/Kolkata"
# 21:26 IST on 15 Nov 2026
NOW = datetime(2026, 11, 15, 15, 56, tzinfo=UTC)


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "t.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    for module in (events_tools, reminders_tools, tasks_tools):
        monkeypatch.setattr(module, "_utc_now", lambda: NOW)


def _assert_plain(result: dict) -> None:
    assert "error" in result and "user_message" in result
    for text in (result["error"], result["user_message"]):
        assert "datetime.datetime" not in text and "zoneinfo" not in text


def test_event_create_in_the_past_explains_and_suggests_tomorrow():
    conn = _conn()
    try:
        out = events_tools.event_create(conn, "t", {"title": "Focus", "when_text": "today 4pm", "tz": TZ})
        _assert_plain(out)
        assert "tomorrow" in out["error"].lower()
        assert "already passed" in out["user_message"].lower()
    finally:
        conn.close()


def test_event_create_unparseable_time_is_plain():
    conn = _conn()
    try:
        out = events_tools.event_create(conn, "t", {"title": "Focus", "when_text": "blorp", "tz": TZ})
        _assert_plain(out)
        assert "understand" in out["user_message"].lower()
    finally:
        conn.close()


def test_reminder_create_in_the_past_is_plain():
    conn = _conn()
    try:
        out = reminders_tools.reminder_create(conn, "t", {"title": "x", "when_text": "today 4pm", "tz": TZ})
        _assert_plain(out)
        assert "tomorrow" in out["error"].lower()
    finally:
        conn.close()


def test_task_create_with_past_due_time_is_plain():
    conn = _conn()
    try:
        out = tasks_tools.task_create(conn, "t", {"title": "x", "when_text": "today 4pm", "tz": TZ})
        _assert_plain(out)
    finally:
        conn.close()
