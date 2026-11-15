"""Undo (plan 8.4): class-B tools record their inverse; Controller.undo replays it."""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

import secretary.tools.reminders as reminders_module
import secretary.tools.tasks as tasks_module
from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import events as events_repo
from secretary.store.repos import notes as notes_repo
from secretary.store.repos import reminders as reminders_repo
from secretary.store.repos import tasks as tasks_repo
from secretary.store.repos import undo as undo_repo
from secretary.tools.events import event_create
from secretary.tools.notes import note_add
from secretary.tools.reminders import reminder_cancel, reminder_create
from secretary.tools.tasks import task_complete, task_create, task_delete, task_update

TZ = "Asia/Kolkata"
NOW = datetime(2026, 11, 15, 4, 30, tzinfo=UTC)


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "u.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(tasks_module, "_utc_now", lambda: NOW)
    monkeypatch.setattr(reminders_module, "_utc_now", lambda: NOW)


def _entries(conn, turn_id):
    return conn.read(lambda c: undo_repo.list_for_turn(c, turn_id))


def test_task_create_records_an_undo_that_removes_the_task():
    conn = _conn()
    try:
        controller = Controller(conn)
        out = task_create(conn, "turn-1", {"title": "buy milk"})
        (entry,) = _entries(conn, "turn-1")
        assert "buy milk" in entry["label"]
        assert controller.undo(entry["id"]) is True
        assert tasks_repo.get(conn, out["task_id"]) is None
    finally:
        conn.close()


def test_a_duplicate_create_records_no_second_undo():
    conn = _conn()
    try:
        task_create(conn, "turn-1", {"title": "buy milk"})
        task_create(conn, "turn-2", {"title": "buy milk"})
        assert len(_entries(conn, "turn-2")) == 0
    finally:
        conn.close()


def test_undo_twice_is_refused_the_second_time():
    conn = _conn()
    try:
        controller = Controller(conn)
        task_create(conn, "t", {"title": "x"})
        (entry,) = _entries(conn, "t")
        assert controller.undo(entry["id"]) is True
        assert controller.undo(entry["id"]) is False
        assert _entries(conn, "t") == []  # undone entries are no longer offered
    finally:
        conn.close()


def test_complete_delete_and_update_are_reversible():
    conn = _conn()
    try:
        controller = Controller(conn)
        made = task_create(conn, "t0", {"title": "report", "notes": "keep", "priority": 0})
        tid = str(made["task_id"])

        task_complete(conn, "t1", {"task_ref": tid})
        assert tasks_repo.get(conn, made["task_id"])["status"] == "done"
        controller.undo(_entries(conn, "t1")[0]["id"])
        row = tasks_repo.get(conn, made["task_id"])
        assert row["status"] == "open" and row["completed_at"] is None

        task_update(conn, "t2", {"task_ref": tid, "title": "final report", "priority": 1})
        controller.undo(_entries(conn, "t2")[0]["id"])
        row = tasks_repo.get(conn, made["task_id"])
        assert (row["title"], row["priority"], row["notes"]) == ("report", 0, "keep")

        task_delete(conn, "t3", {"task_ref": tid})
        assert tasks_repo.get(conn, made["task_id"]) is None
        controller.undo(_entries(conn, "t3")[0]["id"])
        assert tasks_repo.get(conn, made["task_id"])["title"] == "report"
    finally:
        conn.close()


def test_note_add_is_reversible():
    conn = _conn()
    try:
        out = note_add(conn, "t", {"text": "remember this"})
        Controller(conn).undo(_entries(conn, "t")[0]["id"])
        assert notes_repo.get(conn, out["note_id"]) is None
    finally:
        conn.close()


def test_reminder_create_and_cancel_are_reversible_until_they_fire():
    conn = _conn()
    try:
        controller = Controller(conn)
        made = reminder_create(conn, "t1", {"title": "stand up", "when_text": "in 10 minutes", "tz": TZ})
        rid = made["reminder_id"]
        controller.undo(_entries(conn, "t1")[0]["id"])
        assert reminders_repo.get(conn, rid) is None

        made = reminder_create(conn, "t2", {"title": "stretch", "when_text": "in 20 minutes", "tz": TZ})
        reminder_cancel(conn, "t3", {"reminder_ref": str(made["reminder_id"])})
        assert reminders_repo.get(conn, made["reminder_id"]) is None
        assert controller.undo(_entries(conn, "t3")[0]["id"]) is True
        assert reminders_repo.get(conn, made["reminder_id"]) is not None

        # Once a reminder has fired, undoing its creation is not offered.
        fired = reminder_create(conn, "t4", {"title": "fired", "when_text": "in 5 minutes", "tz": TZ})
        conn.execute("UPDATE reminders SET status='done' WHERE id=?", (fired["reminder_id"],))
        assert controller.undo(_entries(conn, "t4")[0]["id"]) is False
        assert reminders_repo.get(conn, fired["reminder_id"]) is not None
    finally:
        conn.close()


def test_event_create_undo_only_before_it_reaches_google():
    conn = _conn()
    try:
        controller = Controller(conn)
        out = event_create(conn, "t1", {"title": "Dentist", "when_text": "in 3 days at 5pm", "tz": TZ})
        assert controller.undo(_entries(conn, "t1")[0]["id"]) is True
        assert events_repo.get(conn, out["event_id"]) is None

        out2 = event_create(conn, "t2", {"title": "Lunch", "when_text": "in 4 days at 1pm", "tz": TZ})
        events_repo.set_sync_state(conn, out2["event_id"], "synced")
        assert controller.undo(_entries(conn, "t2")[0]["id"]) is False
        assert events_repo.get(conn, out2["event_id"]) is not None
    finally:
        conn.close()


def test_turn_finished_announces_the_turns_undo_entries():
    conn = _conn()
    try:
        controller = Controller(conn)
        announced: list[list] = []
        controller.undo_available.connect(announced.append)
        task_create(conn, "turn-9", {"title": "x"})

        class _Done:
            def result(self):
                return "ok"

        controller._on_turn_done("turn-9", _Done())
        assert len(announced) == 1 and len(announced[0]) == 1
        assert announced[0][0]["label"].startswith("Added task")
        assert "token" in announced[0][0]
    finally:
        conn.close()


def test_unknown_token_is_a_safe_noop():
    conn = _conn()
    try:
        assert Controller(conn).undo(99999) is False
    finally:
        conn.close()
