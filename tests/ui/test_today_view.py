"""Today screen (plan 12.2): reminders with Snooze/Done, approvals waiting, While-you-were-away,
today's events and due tasks in time order, quick-add, Plan my day."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from secretary.config import load_config
from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import events as events_repo
from secretary.store.repos import inbox as inbox_repo
from secretary.store.repos import messages as messages_repo
from secretary.store.repos import reminders as reminders_repo
from secretary.store.repos import tasks as tasks_repo
from secretary.tools.email import email_send_prepare
from secretary.ui.main_window import MainWindow
from secretary.ui.views.today import TodayView


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "today.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


def _zone() -> ZoneInfo:
    return ZoneInfo(load_config().app.timezone or "UTC")


def _local(day_offset: int, hour: int, minute: int = 0) -> datetime:
    today = datetime.now(UTC).astimezone(_zone()).date() + timedelta(days=day_offset)
    return datetime(today.year, today.month, today.day, hour, minute, tzinfo=_zone())


def _utc_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _texts(view) -> list[str]:
    QApplication.processEvents()  # widgets added to a visible parent are shown by a queued call
    return [label.text() for label in view.findChildren(QLabel) if not label.isHidden()]


def _buttons(view) -> dict[str, QPushButton]:
    QApplication.processEvents()
    return {b.text(): b for b in view.findChildren(QPushButton) if not b.isHidden()}


# ------------------------------------------------------------------ agenda


def test_agenda_lists_todays_events_and_due_tasks_in_time_order(qapp):
    conn = _conn()
    try:
        events_repo.create(conn, title="Standup", start_at=_local(0, 9).isoformat(),
                           end_at=_local(0, 10).isoformat(), tz=str(_zone()), turn_id="s")
        tasks_repo.create(conn, title="File taxes", due_at=_utc_iso(_local(0, 18)))
        tasks_repo.create(conn, title="Lunch with Asha prep", due_at=_utc_iso(_local(0, 13)))
        events_repo.create(conn, title="Tomorrow thing", start_at=_local(1, 9).isoformat(),
                           end_at=_local(1, 10).isoformat(), tz=str(_zone()), turn_id="s")
        tasks_repo.create(conn, title="Later task", due_at=_utc_iso(_local(3, 9)))
        tasks_repo.create(conn, title="No date task")
        agenda = Controller(conn).today_agenda()
        assert [row["title"] for row in agenda] == ["Standup", "Lunch with Asha prep", "File taxes"]
        assert agenda[0]["kind"] == "event" and agenda[0]["time"] == "09:00"
        assert agenda[2]["kind"] == "task" and agenda[2]["time"] == "18:00"
    finally:
        conn.close()


def test_overdue_tasks_come_first_and_all_day_events_next(qapp):
    conn = _conn()
    try:
        tasks_repo.create(conn, title="Old bill", due_at=_utc_iso(_local(-2, 12)))
        events_repo.create(conn, title="Holiday", start_at=_local(0, 0).isoformat(),
                           end_at=_local(1, 0).isoformat(), tz=str(_zone()), all_day=1, turn_id="s")
        events_repo.create(conn, title="Standup", start_at=_local(0, 9).isoformat(),
                           end_at=_local(0, 10).isoformat(), tz=str(_zone()), turn_id="s")
        agenda = Controller(conn).today_agenda()
        assert [row["title"] for row in agenda] == ["Old bill", "Holiday", "Standup"]
        assert agenda[0]["time"] == "Overdue" and agenda[1]["time"] == "All day"
    finally:
        conn.close()


def test_done_tasks_and_deleted_events_are_not_listed(qapp):
    conn = _conn()
    try:
        done = tasks_repo.create(conn, title="Finished", due_at=_utc_iso(_local(0, 12)))
        tasks_repo.update(conn, done, status="done")
        gone = events_repo.create(conn, title="Cancelled", start_at=_local(0, 9).isoformat(),
                                  end_at=_local(0, 10).isoformat(), tz=str(_zone()), turn_id="s")
        conn.write(lambda c: c.execute("UPDATE events SET deleted_at='2026-01-01T00:00:00Z' WHERE id=?", (gone,)))
        assert Controller(conn).today_agenda() == []
    finally:
        conn.close()


def test_view_shows_agenda_rows_and_an_empty_message(qapp):
    conn = _conn()
    try:
        view = TodayView(Controller(conn))
        view.show()
        assert "Nothing is scheduled for today." in _texts(view)
        events_repo.create(conn, title="Standup", start_at=_local(0, 9).isoformat(),
                           end_at=_local(0, 10).isoformat(), tz=str(_zone()), turn_id="s")
        view.refresh()
        joined = " | ".join(_texts(view))
        assert "Standup" in joined and "09:00" in joined
        assert "Nothing is scheduled for today." not in _texts(view)
    finally:
        conn.close()


# ------------------------------------------------------------------ reminders


def test_reminder_rows_have_snooze_and_done(qapp):
    conn = _conn()
    try:
        item = inbox_repo.create(conn, kind="reminder", title="Take medicine", body="After breakfast.", turn_id="s")
        controller = Controller(conn)
        view = TodayView(controller)
        view.show()
        assert "Take medicine" in " | ".join(_texts(view))
        buttons = _buttons(view)
        assert "Done" in buttons and "Snooze" in buttons
        buttons["Done"].click()
        assert inbox_repo.get(conn, item)["status"] == "done"
        assert "Take medicine" not in " | ".join(_texts(view))
    finally:
        conn.close()


def test_snooze_menu_snoozes_the_reminder(qapp):
    conn = _conn()
    try:
        item = inbox_repo.create(conn, kind="reminder", title="Call mum", body="", turn_id="s")
        view = TodayView(Controller(conn))
        view.show()
        snooze = _buttons(view)["Snooze"]
        action = next(a for a in snooze.menu().actions() if a.text() == "1 hour")
        action.trigger()
        row = inbox_repo.get(conn, item)
        assert row["status"] == "snoozed" and row["snoozed_until"]
        assert "Call mum" not in " | ".join(_texts(view))
    finally:
        conn.close()


def test_done_on_a_task_linked_reminder_asks_about_the_task(qapp, monkeypatch):
    conn = _conn()
    try:
        task = tasks_repo.create(conn, title="Pay rent")
        item = inbox_repo.create(conn, kind="reminder", title="Pay rent", body="", turn_id="s")
        controller = Controller(conn)
        monkeypatch.setattr(controller, "linked_task_for_inbox", lambda _id: {"id": task, "title": "Pay rent"})
        view = TodayView(controller)
        view.show()
        monkeypatch.setattr(view, "_ask_complete_task", lambda title: True)
        _buttons(view)["Done"].click()
        assert inbox_repo.get(conn, item)["status"] == "done"
        assert tasks_repo.get(conn, task)["status"] == "done"
    finally:
        conn.close()


# ------------------------------------------------------------------ approvals, away card, quick-add


def test_approvals_card_appears_only_when_something_waits_and_navigates(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        view = TodayView(controller)
        view.show()
        assert not view._approvals_card.isVisible()
        draft = messages_repo.create(
            conn, from_addr="me@example.com", to_addrs='["ravi@example.com"]', subject="Hello",
            body="Hi", received_at="2026-11-09T09:00:00+00:00", source="draft", turn_id="s")
        email_send_prepare(conn, "t-1", {"draft_ref": str(draft)})
        view.refresh()
        assert view._approvals_card.isVisible()
        assert "1 approval" in view._approvals_text.text()
        seen: list[str] = []
        view.navigate_requested.connect(seen.append)
        view._review_approvals.click()
        assert seen == ["Approvals"]
    finally:
        conn.close()


def test_while_you_were_away_card(qapp):
    conn = _conn()
    try:
        view = TodayView(Controller(conn))
        view.show()
        assert not view._away_card.isVisible()
        inbox_repo.create(conn, kind="while_away", title="While you were away",
                          body="2 reminders fired while Secretary was closed.", turn_id="s")
        view.refresh()
        assert view._away_card.isVisible() and "2 reminders" in view._away_card.text()
    finally:
        conn.close()


def test_quick_add_creates_a_task_or_a_reminder(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        view = TodayView(controller)
        view.show()
        view._input.setText("buy milk")
        view._on_add()
        assert [t["title"] for t in controller.list_tasks()] == ["buy milk"]
        view._input.setText("remind me to stretch in 2 hours")
        view._on_add()
        assert [r["title"] for r in reminders_repo.list_all(conn)] == ["remind me to stretch in 2 hours"]
        view._input.setText("remind me to never")
        view._on_add()
        assert "Couldn't parse a time" in " | ".join(_texts(view))
    finally:
        conn.close()


# ------------------------------------------------------------------ Plan my day


def test_plan_my_day_asks_the_main_window_to_open_the_planner(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        window = MainWindow(controller)
        window.show()
        view = window._views["Today"]
        _buttons(view)["Plan my day"].click()
        assert window._stack.currentWidget() is window._views["Planner"]
        assert window._views["Planner"]._status.isVisible() or window._views["Planner"]._error.isVisible()
    finally:
        conn.close()


def test_approvals_review_button_switches_the_main_window(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        window = MainWindow(controller)
        window.show()
        window._views["Today"].navigate_requested.emit("Approvals")
        assert window._stack.currentWidget() is window._views["Approvals"]
    finally:
        conn.close()
