"""Inbox view tests (offscreen)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import tempfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import inbox as inbox_repo
from secretary.ui.views.inbox import InboxView


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "inbox.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_inbox_view_empty_state(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        view = InboxView(controller)
        view.show()
        assert view._empty.isVisible()
        assert not view._list.isVisible()
        titles = [lbl.text() for lbl in view.findChildren(QLabel)]
        assert any(t.startswith("Nothing needs your attention") for t in titles)
    finally:
        conn.close()


def test_inbox_view_shows_items(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        inbox_repo.create(
            conn,
            kind="reminder",
            title="Buy groceries",
            body="Milk and eggs.",
            turn_id="seed",
        )
        view = InboxView(controller)
        view.show()
        assert not view._empty.isVisible()
        assert view._list.isVisible()
        assert view._list.count() == 1
    finally:
        conn.close()
