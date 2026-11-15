"""Mail view: Gmail triage results (category, urgency, suggested action)."""

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
from secretary.store.repos import messages as messages_repo
from secretary.ui.main_window import MainWindow
from secretary.ui.views.mail import MailView


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "m.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


def _triaged(conn, subject, category, urgency, action, received="2026-11-15T03:00:00Z"):
    mid = messages_repo.create(
        conn, from_addr="boss@example.com", to_addrs='["me@example.com"]', subject=subject,
        body="body", received_at=received, source="gmail", turn_id="s")
    messages_repo.upsert_triage_result(conn, mid, category, urgency, action, "s")
    return mid


def _texts(widget) -> str:
    return " | ".join(label.text() for label in widget.findChildren(QLabel))


def test_controller_lists_triage_results_newest_first():
    conn = _conn()
    try:
        _triaged(conn, "Older", "work", "low", "read", "2026-11-14T03:00:00Z")
        _triaged(conn, "Newer", "invoice", "high", "reply", "2026-11-15T03:00:00Z")
        rows = Controller(conn).list_triage()
        assert [r["subject"] for r in rows] == ["Newer", "Older"]
        assert rows[0]["category"] == "invoice"
    finally:
        conn.close()


def test_view_shows_each_message_with_its_classification(qapp):
    conn = _conn()
    try:
        _triaged(conn, "Invoice 42 due", "invoice", "high", "reply")
        view = MailView(Controller(conn))
        view.show()
        assert view._list.count() == 1
        text = _texts(view._list.itemWidget(view._list.item(0)))
        assert "Invoice 42 due" in text and "boss@example.com" in text
        assert "Invoice" in text and "High" in text and "Reply" in text
    finally:
        conn.close()


def test_view_explains_itself_and_has_an_empty_state(qapp):
    conn = _conn()
    try:
        view = MailView(Controller(conn))
        view.show()
        assert "classified" in _texts(view).lower()
        assert view._empty.isVisible() and not view._list.isVisible()
        assert "Google" in view._empty._title.text()
    finally:
        conn.close()


def test_view_refreshes_when_shown(qapp):
    conn = _conn()
    try:
        view = MailView(Controller(conn))
        assert view._list.count() == 0
        _triaged(conn, "Late arrival", "work", "normal", "read")
        view.refresh()
        assert view._list.count() == 1
    finally:
        conn.close()


def test_mail_is_in_the_navigation_rail(qapp):
    conn = _conn()
    try:
        window = MainWindow(Controller(conn))
        labels = [window._rail.item(i).text() for i in range(window._rail.count())]
        assert "Mail" in labels
        assert isinstance(window._views["Mail"], MailView)
    finally:
        conn.close()
