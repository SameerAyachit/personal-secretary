"""Approvals view (offscreen)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import tempfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import messages as messages_repo
from secretary.tools.email import email_send_prepare
from secretary.ui.views.approvals import ApprovalsView


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "ap.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con, migrations_folder(), lambda: None)
    return con


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_approvals_view_shows_recipients_and_highlights_new(qapp):
    conn = _conn()
    try:
        messages_repo.create(
            conn, from_addr="boss@example.com", to_addrs='["me@example.com"]',
            subject="Old", body="Old mail", received_at="2026-11-09T08:00:00+00:00", turn_id="s")
        draft_id = messages_repo.create(
            conn, from_addr="me@example.com", to_addrs='["ravi@example.com"]',
            subject="Draft", body="Body text here",
            received_at="2026-11-09T09:00:00+00:00", source="draft", turn_id="s")
        email_send_prepare(conn, "t-1", {"draft_ref": str(draft_id)})
        controller = Controller(conn)
        view = ApprovalsView(controller)
        text = "".join(
            lbl.text() for lbl in view.findChildren(QLabel)
        )
        assert "To:" in text
        assert "ravi@example.com (new)" in text
        assert "Body text here" in text
        assert view._list.count() == 1
    finally:
        conn.close()


def test_approvals_view_empty_state(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        view = ApprovalsView(controller)
        view.show()
        assert view._empty.isVisible()
        assert not view._title.isVisible()
        assert view._list.count() == 0
    finally:
        conn.close()


def test_approvals_view_lists_drafts_with_actions(qapp):
    raw = _conn()
    db_path = raw.execute("PRAGMA database_list").fetchone()[2]
    raw.close()
    conn = Connection(Path(db_path))
    try:
        draft_id = messages_repo.create(
            conn, from_addr="me", to_addrs='["ravi@example.com"]', subject="Lunch plan",
            body="See you at noon", received_at="2026-11-09T09:00:00+00:00",
            source="draft", turn_id="s")
        controller = Controller(conn)
        view = ApprovalsView(controller)
        text = "".join(lbl.text() for lbl in view.findChildren(QLabel))
        assert "Drafts" in text
        assert "Lunch plan" in text
        assert "ravi@example.com" in text
        assert view._drafts.count() == 1

        def live_buttons():
            row = view._drafts.itemWidget(view._drafts.item(0))
            return {b.text(): b for b in row.findChildren(QPushButton)}

        buttons = live_buttons()
        assert set(buttons) == {"Request send", "Discard"}
        buttons["Request send"].click()
        # The draft now has a waiting approval and the approvals list shows it.
        assert view._list.count() == 1
        row = view._drafts.itemWidget(view._drafts.item(0))
        assert "Send request pending" in "".join(lbl.text() for lbl in row.findChildren(QLabel))
        buttons = live_buttons()
        assert "Request send" not in buttons
        buttons["Discard"].click()
        assert view._drafts.count() == 0
        assert messages_repo.get(conn, draft_id) is None
    finally:
        conn.close()
