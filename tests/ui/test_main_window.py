"""UI tests (offscreen, plan §12 / secretary-ui-design skill)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import tempfile
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.ui.main_window import MainWindow
from secretary.ui.views.tasks import TasksView


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "ui.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def controller(qapp):
    return Controller(_conn())


def test_main_window_hides_instead_of_quitting(qapp, controller):
    app = QApplication.instance()
    assert app is not None
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow(controller)
    window.show()
    assert window.isVisible()
    event = QCloseEvent()
    window.closeEvent(event)
    assert not window.isVisible()
    # The application must still be running (not quit).
    assert QApplication.instance() is not None


def test_rail_switches_views(qapp, controller):
    window = MainWindow(controller)
    # Switch rail to Tasks.
    window._rail.setCurrentRow(2)  # Tasks
    assert window._stack.currentWidget() is window._views["Tasks"]


def test_tasks_quick_add_without_llm(qapp, controller):
    """Manual quick-add works without the LLM (P1-08 acceptance)."""
    view = TasksView(controller)
    view._input.setText("submit the lab report")
    view._on_add()
    assert view._input.text() == ""
    # Task persisted in the store.
    rows = controller.list_tasks()
    assert any("submit the lab report" in r["title"] for r in rows)
    view.refresh()
    titles = view.titles()
    assert "submit the lab report" in titles


def test_opening_a_view_refreshes_it(qapp, controller):
    window = MainWindow(controller)
    approvals = window._views["Approvals"]
    calls: list[int] = []
    approvals.refresh = lambda: calls.append(1)  # type: ignore[method-assign]
    for row in range(window._rail.count()):
        if window._rail.item(row).data(Qt.UserRole) == "Approvals":
            window._rail.setCurrentRow(row)
    assert calls == [1]


def test_turn_done_refreshes_approvals_and_inbox(qapp, controller):
    seen: list[str] = []
    controller.approvals_changed.connect(lambda: seen.append("approvals"))
    controller.inbox_changed.connect(lambda: seen.append("inbox"))
    controller.tasks_changed.connect(lambda: seen.append("tasks"))

    class _Done:
        def result(self):
            return "ok"

    controller._on_turn_done("turn-x", _Done())
    assert {"approvals", "inbox", "tasks"} <= set(seen)
