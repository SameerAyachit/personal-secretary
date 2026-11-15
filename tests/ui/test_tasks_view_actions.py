"""Tasks view: filter chips, search, complete, inline edit and delete (plan 12.2)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit, QPushButton

from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import tasks as tasks_repo
from secretary.ui.views.tasks import TasksView


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "t.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _iso(delta: timedelta) -> str:
    return (datetime.now(UTC) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed(conn):
    ids = {
        "overdue": tasks_repo.create(conn, title="Pay the electricity bill", due_at=_iso(timedelta(days=-2))),
        "today": tasks_repo.create(conn, title="Call the dentist", due_at=_iso(timedelta(minutes=30))),
        "later": tasks_repo.create(conn, title="Read chapter five", notes="for the course",
                                   due_at=_iso(timedelta(days=9))),
        "nodate": tasks_repo.create(conn, title="Buy groceries"),
    }
    ids["done"] = tasks_repo.create(conn, title="Old finished chore")
    tasks_repo.update(conn, ids["done"], status="done", completed_at=_iso(timedelta(days=-1)))
    return ids


def _row_buttons(view, index=0):
    return {b.text(): b for b in view._list.itemWidget(view._list.item(index)).findChildren(QPushButton)}


def test_default_shows_open_tasks_and_chips_filter_them(qapp):
    conn = _conn()
    try:
        _seed(conn)
        view = TasksView(Controller(conn))
        view.show()
        assert len(view.titles()) == 4 and "Old finished chore" not in view.titles()
        view.set_filter("overdue")
        assert view.titles() == ["Pay the electricity bill"]
        view.set_filter("done")
        assert view.titles() == ["Old finished chore"]
        view.set_filter("today")
        assert "Call the dentist" in view.titles() and "Read chapter five" not in view.titles()
    finally:
        conn.close()


def test_search_matches_title_and_notes(qapp):
    conn = _conn()
    try:
        _seed(conn)
        view = TasksView(Controller(conn))
        view.show()
        view._search.setText("course")
        assert view.titles() == ["Read chapter five"]  # matched through its notes
        view._search.setText("groc")
        assert view.titles() == ["Buy groceries"]
        view._search.setText("zzz")
        assert view.titles() == [] and view._empty.isVisible()
    finally:
        conn.close()


def test_ticking_the_box_completes_the_task_and_unticking_reopens_it(qapp):
    conn = _conn()
    try:
        ids = _seed(conn)
        view = TasksView(Controller(conn))
        view.show()
        view._list.itemWidget(view._list.item(view.titles().index("Buy groceries"))).findChild(QCheckBox).click()
        assert tasks_repo.get(conn, ids["nodate"])["status"] == "done"
        assert "Buy groceries" not in view.titles()
        view.set_filter("done")
        index = view.titles().index("Buy groceries")
        view._list.itemWidget(view._list.item(index)).findChild(QCheckBox).click()
        assert tasks_repo.get(conn, ids["nodate"])["status"] == "open"
    finally:
        conn.close()


def test_inline_edit_renames_and_cancel_keeps_the_title(qapp):
    conn = _conn()
    try:
        ids = _seed(conn)
        view = TasksView(Controller(conn))
        view.show()
        index = view.titles().index("Buy groceries")
        buttons = _row_buttons(view, index)
        buttons["Edit"].click()
        row = view._list.itemWidget(view._list.item(index))
        row.findChild(QLineEdit).setText("Buy groceries and milk")
        _row_buttons(view, index)["Cancel"].click()
        assert tasks_repo.get(conn, ids["nodate"])["title"] == "Buy groceries"
        _row_buttons(view, index)["Edit"].click()
        view._list.itemWidget(view._list.item(index)).findChild(QLineEdit).setText("Buy groceries and milk")
        _row_buttons(view, index)["Save"].click()
        assert tasks_repo.get(conn, ids["nodate"])["title"] == "Buy groceries and milk"
        assert "Buy groceries and milk" in view.titles()
    finally:
        conn.close()


def test_blank_title_is_not_saved(qapp):
    conn = _conn()
    try:
        ids = _seed(conn)
        view = TasksView(Controller(conn))
        view.show()
        index = view.titles().index("Buy groceries")
        _row_buttons(view, index)["Edit"].click()
        view._list.itemWidget(view._list.item(index)).findChild(QLineEdit).setText("   ")
        _row_buttons(view, index)["Save"].click()
        assert tasks_repo.get(conn, ids["nodate"])["title"] == "Buy groceries"
    finally:
        conn.close()


def test_delete_removes_the_task_from_the_list(qapp):
    conn = _conn()
    try:
        ids = _seed(conn)
        view = TasksView(Controller(conn))
        view.show()
        index = view.titles().index("Buy groceries")
        _row_buttons(view, index)["Delete"].click()
        assert tasks_repo.get(conn, ids["nodate"]) is None
        assert "Buy groceries" not in view.titles()
    finally:
        conn.close()


def test_due_time_is_shown_in_local_time(qapp):
    conn = _conn()
    try:
        tasks_repo.create(conn, title="Submit report", due_at="2026-11-16T10:30:00Z")
        controller = Controller(conn)
        view = TasksView(controller)
        view.show()
        texts = " | ".join(lbl.text() for lbl in view._list.itemWidget(view._list.item(0)).findChildren(type(view._status)))
        assert "16 Nov" in texts
    finally:
        conn.close()


def test_controller_filter_helpers():
    conn = _conn()
    try:
        _seed(conn)
        controller = Controller(conn)
        assert len(controller.list_tasks()) == 4  # unchanged: open tasks
        assert [t["title"] for t in controller.list_tasks("overdue")] == ["Pay the electricity bill"]
        assert [t["title"] for t in controller.list_tasks("done")] == ["Old finished chore"]
        assert [t["title"] for t in controller.list_tasks("open", "dentist")] == ["Call the dentist"]
    finally:
        conn.close()
