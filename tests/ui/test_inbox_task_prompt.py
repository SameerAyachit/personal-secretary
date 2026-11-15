"""Done on a reminder that belongs to a task offers to complete the task too (plan 10.3)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import tempfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import inbox as inbox_repo
from secretary.store.repos import reminders as reminders_repo
from secretary.store.repos import tasks as tasks_repo
from secretary.ui.views.inbox import InboxView


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "i.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _linked_item(conn, task_title="Submit report"):
    tid = tasks_repo.create(conn, title=task_title, source="user")
    rid = reminders_repo.create(conn, task_id=tid, title="report", body="", kind="once", tz="UTC",
                                rule_json=None, next_fire_at="2026-11-16T04:00:00+00:00")
    iid = inbox_repo.create(conn, kind="reminder", title="report", body="", reminder_id=rid)
    return tid, iid


def _click_done(view):
    row = view._list.itemWidget(view._list.item(0))
    next(b for b in row.findChildren(QPushButton) if b.text() == "Done").click()


def _status(conn, tid):
    return tasks_repo.get(conn, tid)["status"]


def test_controller_finds_the_open_task_behind_an_inbox_item():
    conn = _conn()
    try:
        tid, iid = _linked_item(conn)
        assert Controller(conn).linked_task_for_inbox(iid)["id"] == tid
        plain = inbox_repo.create(conn, kind="system", title="x", body="")
        assert Controller(conn).linked_task_for_inbox(plain) is None
    finally:
        conn.close()


def test_done_can_also_complete_the_task():
    conn = _conn()
    try:
        tid, iid = _linked_item(conn)
        controller = Controller(conn)
        changed = []
        controller.tasks_changed.connect(lambda: changed.append(1))
        controller.done_inbox(iid, complete_task=True)
        assert inbox_repo.get(conn, iid)["status"] == "done" and _status(conn, tid) == "done"
        assert changed == [1]
    finally:
        conn.close()


def test_view_asks_and_yes_completes_the_task(qapp, monkeypatch):
    conn = _conn()
    try:
        tid, iid = _linked_item(conn)
        view = InboxView(Controller(conn))
        view.show()
        asked = []
        monkeypatch.setattr(view, "_ask_complete_task", lambda title: asked.append(title) or True)
        _click_done(view)
        assert asked == ["Submit report"]
        assert inbox_repo.get(conn, iid)["status"] == "done" and _status(conn, tid) == "done"
    finally:
        conn.close()


def test_view_no_keeps_the_task_open(qapp, monkeypatch):
    conn = _conn()
    try:
        tid, iid = _linked_item(conn)
        view = InboxView(Controller(conn))
        view.show()
        monkeypatch.setattr(view, "_ask_complete_task", lambda title: False)
        _click_done(view)
        assert inbox_repo.get(conn, iid)["status"] == "done" and _status(conn, tid) == "open"
    finally:
        conn.close()


def test_view_cancel_changes_nothing(qapp, monkeypatch):
    conn = _conn()
    try:
        tid, iid = _linked_item(conn)
        view = InboxView(Controller(conn))
        view.show()
        monkeypatch.setattr(view, "_ask_complete_task", lambda title: None)
        _click_done(view)
        assert inbox_repo.get(conn, iid)["status"] == "unacknowledged" and _status(conn, tid) == "open"
    finally:
        conn.close()


def test_unlinked_item_is_done_without_a_question(qapp, monkeypatch):
    conn = _conn()
    try:
        iid = inbox_repo.create(conn, kind="reminder", title="plain", body="")
        view = InboxView(Controller(conn))
        view.show()
        monkeypatch.setattr(view, "_ask_complete_task", lambda title: pytest.fail("must not ask"))
        _click_done(view)
        assert inbox_repo.get(conn, iid)["status"] == "done"
    finally:
        conn.close()
