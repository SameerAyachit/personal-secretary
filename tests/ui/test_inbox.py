"""Tests for the Inbox view status transitions (plan §10.3, P2-02)."""

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
from secretary.ui.views.inbox import InboxView


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "inbox.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _add_inbox(conn, title="t", body="b"):
    return inbox_repo.create(conn, kind="reminder", title=title, body=body)


def _ack_btn(widget):
    for btn in widget.findChildren(QPushButton):
        if btn.text() == "Ack":
            return btn
    return None


def _done_btn(widget):
    for btn in widget.findChildren(QPushButton):
        if btn.text() == "Done":
            return btn
    return None


def test_inbox_refresh_shows_items(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        _add_inbox(conn, "reminder one", "body one")
        _add_inbox(conn, "reminder two", "body two")
        view = InboxView(controller)
        assert view._list.count() == 2
    finally:
        conn.close()


def test_inbox_ack_transitions_to_acknowledged(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        iid = _add_inbox(conn, "ack me", "body")
        view = InboxView(controller)
        _ack_btn(view._list.itemWidget(view._list.item(0))).click()
        rows = controller.list_inbox()
        assert not any(r["id"] == iid for r in rows)
    finally:
        conn.close()


def test_inbox_done_transitions(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        iid = _add_inbox(conn, "done me", "body")
        view = InboxView(controller)
        _done_btn(view._list.itemWidget(view._list.item(0))).click()
        rows = controller.list_inbox()
        assert not any(r["id"] == iid for r in rows)
    finally:
        conn.close()
