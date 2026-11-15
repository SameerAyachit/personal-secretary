"""Chat shows an Undo button under a reply that changed something."""

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
from secretary.store.repos import tasks as tasks_repo
from secretary.store.repos import undo as undo_repo
from secretary.tools.tasks import task_create
from secretary.ui.views.chat import ChatView


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "c.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


def _undo_buttons(view):
    return [b for b in view.findChildren(QPushButton) if b.text().startswith(("Undo", "Undone"))]


def test_undo_button_appears_and_undoes_then_disables(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        view = ChatView(controller)
        made = task_create(conn, "turn-1", {"title": "buy milk"})
        entry = conn.read(lambda c: undo_repo.list_for_turn(c, "turn-1"))[0]
        controller.undo_available.emit([{"token": entry["id"], "label": entry["label"]}])
        buttons = _undo_buttons(view)
        assert len(buttons) == 1 and "buy milk" in buttons[0].text()
        buttons[0].click()
        assert tasks_repo.get(conn, made["task_id"]) is None
        assert not buttons[0].isEnabled()
        assert "Undone" in buttons[0].text()
    finally:
        conn.close()
