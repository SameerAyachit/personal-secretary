"""Tasks view tests (offscreen)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import tempfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit

from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.ui.views.tasks import TasksView


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "tasks.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_tasks_view_empty_state(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        view = TasksView(controller)
        view.show()
        assert view._empty.isVisible()
        assert not view._list.isVisible()
        titles = [lbl.text() for lbl in view.findChildren(QLabel)]
        assert "No tasks yet." in titles
    finally:
        conn.close()


def test_tasks_view_shows_created_tasks(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        controller.create_task_manual("buy groceries", "")
        view = TasksView(controller)
        view.show()
        assert not view._empty.isVisible()
        assert view._list.isVisible()
        assert view._list.count() == 1
        item = view._list.item(0)
        assert item.data(256 + 1) == "buy groceries"
        # The quick-add input should still be present and focusable.
        assert isinstance(view.findChild(QLineEdit), QLineEdit)
    finally:
        conn.close()


def test_tasks_view_add_task_focuses_input(qapp):
    from unittest.mock import patch  # noqa: PLC0415

    conn = _conn()
    try:
        controller = Controller(conn)
        view = TasksView(controller)
        view.show()
        with patch.object(view._input, "setFocus") as mock_focus:
            view._empty._action.click()
            mock_focus.assert_called_once()
    finally:
        conn.close()
