"""The Inbox explains itself: subtitle, kind badges, local times, Open for research."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import tempfile
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import inbox as inbox_repo
from secretary.store.repos import messages as messages_repo
from secretary.store.repos import research_briefs as briefs_repo
from secretary.tools.email import email_send_prepare
from secretary.ui.main_window import MainWindow
from secretary.ui.views.inbox import InboxView, format_local_time, kind_label


def _conn() -> Connection:
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


def test_kind_label_from_kind_and_payload():
    assert kind_label({"kind": "reminder", "payload_json": None}) == "Reminder"
    assert kind_label({"kind": "while_away", "payload_json": None}) == "While you were away"
    assert kind_label({"kind": "approval", "payload_json": None}) == "Approval"
    assert kind_label({"kind": "briefing", "payload_json": None}) == "Briefing"
    assert kind_label({"kind": "system", "payload_json": None}) == "System"
    assert kind_label({"kind": "system", "payload_json": "{}"}) == "System"
    assert kind_label({"kind": "system", "payload_json": "not json"}) == "System"
    assert kind_label({"kind": "system", "payload_json": json.dumps({"research_brief_id": 3})}) == "Research"
    assert kind_label({"kind": "system", "payload_json": json.dumps({"email": True})}) == "Email"


def test_format_local_time_uses_the_given_zone():
    assert format_local_time("2026-11-15T03:48:09Z", "Asia/Kolkata") == "15 Nov, 09:18"
    assert format_local_time("2026-11-15T03:48:09+00:00", "UTC") == "15 Nov, 03:48"
    assert format_local_time("garbage", "UTC") == "garbage"
    assert format_local_time("2026-11-15T03:48:09Z", "Not/AZone") == "15 Nov, 03:48"


def _texts(widget) -> str:
    return " | ".join(label.text() for label in widget.findChildren(QLabel))


def test_view_has_a_subtitle_that_explains_the_inbox(qapp):
    conn = _conn()
    try:
        view = InboxView(Controller(conn))
        text = _texts(view)
        assert "notification log" in text
        assert "reminders" in text.lower()
        assert "research" in text.lower()
    finally:
        conn.close()


def test_rows_show_kind_badge_and_time(qapp):
    conn = _conn()
    try:
        inbox_repo.create(conn, kind="reminder", title="Stand up", body="now")
        view = InboxView(Controller(conn))
        row = view._list.itemWidget(view._list.item(0))
        text = _texts(row)
        assert "Reminder" in text
        assert any(ch.isdigit() for ch in text)  # a time stamp
    finally:
        conn.close()


def test_empty_texts_say_what_will_appear(qapp):
    conn = _conn()
    try:
        view = InboxView(Controller(conn))
        view.show()
        new_text = view._empty._title.text()
        assert "Nothing needs your attention" in new_text
        assert "research" in new_text.lower()
        view._filter_buttons["snoozed"].click()
        assert "snoozed" in view._empty._title.text().lower()
    finally:
        conn.close()


def test_open_button_only_on_research_items_and_emits_signal(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        inbox_repo.create(conn, kind="reminder", title="Plain", body="b")
        inbox_repo.create(
            conn, kind="system", title="Research brief ready: batteries", body="b",
            payload_json=json.dumps({"research_brief_id": 7}))
        view = InboxView(controller)
        opened: list[int] = []
        controller.open_research_brief.connect(opened.append)
        rows = [view._list.itemWidget(view._list.item(i)) for i in range(view._list.count())]
        with_open = [r for r in rows if any(b.text() == "Open" for b in r.findChildren(QPushButton))]
        assert len(with_open) == 1
        next(b for b in with_open[0].findChildren(QPushButton) if b.text() == "Open").click()
        assert opened == [7]
    finally:
        conn.close()


def test_email_result_notes_are_labelled_email(qapp):
    class _Gmail:
        def send_message(self, to_addrs, subject, body, user_id="me"):
            return {"id": "g1"}

    conn = _conn()
    try:
        controller = Controller(conn)
        controller._run_background = lambda fn: fn()
        controller.set_gmail_client(_Gmail())
        draft_id = messages_repo.create(
            conn, from_addr="me", to_addrs='["a@b.com"]', subject="S", body="B",
            received_at="2026-11-15T08:00:00+00:00", source="draft", turn_id="s")
        prepared = email_send_prepare(conn, "t", {"draft_ref": str(draft_id)})
        controller.approve_action(str(prepared["pending_id"]))
        rows = controller.list_inbox(None)
        assert len(rows) == 1
        assert kind_label(rows[0]) == "Email"
    finally:
        conn.close()


def test_main_window_opens_the_research_brief(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        brief_id = conn.write(lambda c: briefs_repo.create(c, "batteries"))
        window = MainWindow(controller)
        research = window._views["Research"]
        controller.open_research_brief.emit(brief_id)
        assert window._stack.currentWidget() is research
        current = window._rail.currentItem().data(Qt.UserRole)
        assert current == "Research"
        assert research._rows[research._recent.currentRow()]["id"] == brief_id
    finally:
        conn.close()
