"""Screenshot grabs for the UI review loop (plan §12, skill secretary-ui-design §7).

Grabs every view in light and dark themes (offscreen QT_QPA_PLATFORM)
and saves PNGs under docs/screenshots/. Also runs the programmatic checks the
skill requires when images cannot be inspected directly: labels non-empty and
a cycling tab order.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import events as events_repo
from secretary.store.repos import inbox as inbox_repo
from secretary.store.repos import messages as messages_repo
from secretary.tools.email import email_send_prepare
from secretary.ui.theme import apply_theme
from secretary.ui.views.approvals import ApprovalsView
from secretary.ui.views.chat import ChatView
from secretary.ui.views.events import EventsView
from secretary.ui.views.inbox import InboxView
from secretary.ui.views.settings import SettingsView
from secretary.ui.views.tasks import TasksView
from secretary.ui.views.today import TodayView

OUT = Path("docs/screenshots")


class _DummyConn:
    """Controller only stores the connection."""


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "scr.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con, migrations_folder(), lambda: None)
    return con


def _approvals_conn() -> Connection:
    con = _conn()
    messages_repo.create(
        con, from_addr="me@example.com", to_addrs='["ravi@example.com"]',
        subject="Draft for ravi", body="Hello Ravi",
        received_at="2026-11-09T08:00:00+00:00", source="draft", turn_id="s")
    draft_id = messages_repo.create(
        con, from_addr="me@example.com", to_addrs='["newperson@example.com"]',
        subject="Review", body="Please review this.",
        received_at="2026-11-09T09:00:00+00:00", source="draft", turn_id="s")
    email_send_prepare(con, "t-1", {"draft_ref": str(draft_id)})
    return con


def _grab(app: QApplication, theme: str, view: QWidget, name: str) -> Path:
    apply_theme(app, theme)
    view.resize(900, 600)
    view.show()
    pix = view.grab()
    path = OUT / f"{name}_{theme}_100.png"
    assert pix.save(str(path))
    return path


def test_screenshots_and_checks(tmp_path: Path) -> None:
    os.environ["SECRETARY_DATA_ROOT"] = str(tmp_path)
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    produced: list[Path] = []

    views: list[tuple[str, QWidget]] = []

    # Calendar (events) view: empty and with an event.
    con = _conn()
    try:
        controller = Controller(con)
        views.append(("calendar_empty", EventsView(controller)))
        events_repo.create(
            con, title="Standup", start_at="2026-11-09T04:30:00+00:00",
            end_at="2026-11-09T05:30:00+00:00", tz="Asia/Kolkata", turn_id="s")
        views.append(("calendar_with_event", EventsView(controller)))
    finally:
        con.close()

    # Tasks view: empty and with a task.
    con = _conn()
    try:
        controller = Controller(con)
        views.append(("tasks_empty", TasksView(controller)))
        controller.create_task_manual("buy groceries", "")
        views.append(("tasks_with_item", TasksView(controller)))
    finally:
        con.close()

    # Inbox view: empty and with an item.
    con = _conn()
    try:
        controller = Controller(con)
        views.append(("inbox_empty", InboxView(controller)))
        inbox_repo.create(
            con, kind="reminder", title="Buy groceries", body="Milk and eggs.",
            turn_id="seed")
        views.append(("inbox_with_item", InboxView(controller)))
    finally:
        con.close()

    # Today view: empty and with a reminder + task.
    con = _conn()
    try:
        controller = Controller(con)
        views.append(("today_empty", TodayView(controller)))
        inbox_repo.create(
            con, kind="reminder", title="Take medicine", body="After breakfast.",
            turn_id="seed")
        controller.create_task_manual("file taxes", "")
        views.append(("today_with_items", TodayView(controller)))
    finally:
        con.close()

    # Chat view: empty (its intro text is always shown).
    views.append(("chat_empty", ChatView(Controller(_DummyConn()))))

    # Approvals view: empty and with a pending email send.
    con = _approvals_conn()
    try:
        controller = Controller(con)
        views.append(("approvals_empty", ApprovalsView(controller)))
        views.append(("approvals_with_item", ApprovalsView(controller)))
    finally:
        con.close()

    # Settings view.
    views.append(("settings", SettingsView(Controller(_DummyConn()))))

    for name, view in views:
        for theme in ("light", "dark"):
            produced.append(_grab(app, theme, view, name))

    for path in produced:
        assert path.exists() and path.stat().st_size > 0, path

    # Programmatic checks (skill §7: no empty label text, cycling tab order).
    for _name, view in views:
        view.show()
        view.resize(900, 600)
        for widget in view.findChildren(QWidget):
            if widget.inherits("QLabel") and not widget.isHidden() and not widget.text():
                raise AssertionError(f"empty label text: {widget}")
        focusables = [w for w in view.findChildren(QWidget)
                      if w.focusPolicy() & Qt.TabFocus]
        if focusables:
            first = focusables[0]
            current = first
            for _ in range(50):
                current = current.nextInFocusChain()
                if current is first:
                    break
            else:
                raise AssertionError("tab order chain does not cycle")