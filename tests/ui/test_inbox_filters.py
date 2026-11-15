"""Inbox filters and reversible actions: a choice can always be changed."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import tempfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QInputDialog, QPushButton

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


def _add(conn, title="t"):
    return inbox_repo.create(conn, kind="reminder", title=title, body="b")


def _buttons(view):
    row = view._list.itemWidget(view._list.item(0))
    return {b.text(): b for b in row.findChildren(QPushButton)}


def test_controller_list_inbox_filters_and_all():
    conn = _conn()
    try:
        controller = Controller(conn)
        a, b, c = _add(conn, "a"), _add(conn, "b"), _add(conn, "c")
        controller.ack_inbox(a)
        controller.done_inbox(b)
        assert [r["id"] for r in controller.list_inbox()] == [c]
        assert [r["id"] for r in controller.list_inbox("acknowledged")] == [a]
        assert [r["id"] for r in controller.list_inbox("done")] == [b]
        assert {r["id"] for r in controller.list_inbox(None)} == {a, b, c}
        # The tray badge still counts only items needing attention.
        assert [r["id"] for r in controller.list_inbox_preview()] == [c]
    finally:
        conn.close()


def test_reopen_returns_item_to_new_and_clears_snooze():
    conn = _conn()
    try:
        controller = Controller(conn)
        iid = _add(conn)
        controller.snooze_inbox(iid, "1 hour")
        assert inbox_repo.get(conn, iid)["snoozed_until"]
        controller.reopen_inbox(iid)
        row = inbox_repo.get(conn, iid)
        assert row["status"] == "unacknowledged"
        assert row["snoozed_until"] is None
    finally:
        conn.close()


def test_view_can_switch_filter_and_change_a_choice(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        iid = _add(conn, "walk the dog")
        view = InboxView(controller)
        view.show()
        assert view._list.count() == 1
        _buttons(view)["Ack"].click()
        assert view._list.count() == 0  # leaves the "New" filter

        view._filter_buttons["acknowledged"].click()
        assert view._list.count() == 1
        buttons = _buttons(view)
        assert "Ack" not in buttons  # already acknowledged
        assert {"Snooze", "Done", "Reopen"} <= set(buttons)
        buttons["Done"].click()
        assert inbox_repo.get(conn, iid)["status"] == "done"

        view._filter_buttons["done"].click()
        _buttons(view)["Reopen"].click()
        assert inbox_repo.get(conn, iid)["status"] == "unacknowledged"

        view._filter_buttons["all"].click()
        assert view._list.count() == 1
    finally:
        conn.close()


def test_snooze_button_offers_three_durations_and_custom(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        iid = _add(conn)
        view = InboxView(controller)
        snooze = _buttons(view)["Snooze"]
        labels = [a.text() for a in snooze.menu().actions()]
        assert labels == ["10 minutes", "1 hour", "Tomorrow 9am", "Custom..."]
        snooze.menu().actions()[1].trigger()
        assert inbox_repo.get(conn, iid)["status"] == "snoozed"
    finally:
        conn.close()


def test_empty_text_depends_on_filter(qapp):
    conn = _conn()
    try:
        view = InboxView(Controller(conn))
        view.show()
        assert view._empty._title.text() .startswith("Nothing needs your attention")
        view._filter_buttons["done"].click()
        assert view._empty.isVisible()
        assert "done" in view._empty._title.text().lower()
    finally:
        conn.close()


def test_snooze_menu_has_a_custom_entry_that_uses_the_typed_text(qapp, monkeypatch):
    conn = _conn()
    try:
        controller = Controller(conn)
        iid = _add(conn)
        view = InboxView(controller)
        snooze = _buttons(view)["Snooze"]
        labels = [a.text() for a in snooze.menu().actions()]
        assert labels[-1].startswith("Custom")
        monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("in 3 hours", True)))
        snooze.menu().actions()[-1].trigger()
        assert inbox_repo.get(conn, iid)["status"] == "snoozed"
        assert inbox_repo.get(conn, iid)["snoozed_until"]
        # Cancelling the dialog leaves the item alone.
        controller.reopen_inbox(iid)
        view.refresh()
        monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))
        _buttons(view)["Snooze"].menu().actions()[-1].trigger()
        assert inbox_repo.get(conn, iid)["status"] == "unacknowledged"
    finally:
        conn.close()
