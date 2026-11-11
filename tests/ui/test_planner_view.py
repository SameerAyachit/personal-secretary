"""UI tests for the planner view (offscreen, plan C-54).

Free slots are computed in code by plan_day via the controller; no LLM or
network is needed. Events are inserted directly into the store to block slots.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import events as events_repo
from secretary.ui.views.planner import PlannerView


def _conn(tmp_path: Path) -> Connection:
    db = tmp_path / "planner.db"
    conn = Connection(db)
    migrate(conn._con, migrations_folder(), lambda: None)
    return conn


@pytest.fixture()
def controller(tmp_path) -> Controller:
    return Controller(_conn(tmp_path))


def _add_event(conn: Connection, title: str, start_iso: str, end_iso: str, tz: str = "Asia/Kolkata") -> None:
    events_repo.create(
        conn,
        title=title,
        start_at=start_iso,
        end_at=end_iso,
        tz=tz,
        turn_id="planner-test",
    )


def test_planner_shows_free_slots_and_creates_task(qapp, controller, tmp_path):
    app = QApplication.instance()
    view = PlannerView(controller)
    view._date.setText("2026-11-11")
    view._plan()
    app.processEvents()

    # No events -> free slots span the work day 09:00-17:00.
    assert view._slots.count() >= 1
    first = view._slots.item(0).text()
    assert first.startswith("09:00")
    assert not view._error.isVisible()

    # Create a task in the first slot.
    result = controller.get_free_slots("2026-11-11", "Asia/Kolkata")
    start = result["free_slots"][0]["start"]
    view._slots.setCurrentRow(0)
    view._task_input.setText("Review plan")
    view._create_task()
    assert "Task created: Review plan" in view._status.text()
    tasks = controller.list_tasks()
    assert any(t["title"] == "Review plan" and t["due_at"] == start for t in tasks)


def test_planner_blocks_slots_around_events(qapp, controller, tmp_path):
    app = QApplication.instance()
    tz = ZoneInfo("Asia/Kolkata")
    day = datetime(2026, 11, 11, tzinfo=tz)
    # Block 10:00-11:00.
    _add_event(
        controller.conn,
        "Meeting",
        (day.replace(hour=10)).isoformat(),
        (day.replace(hour=11)).isoformat(),
    )
    view = PlannerView(controller)
    view._date.setText("2026-11-11")
    view._plan()
    app.processEvents()

    labels = [view._slots.item(i).text() for i in range(view._slots.count())]
    joined = " | ".join(labels)
    # 09:00-10:00 slot should exist; no slot should cover 10:00-11:00.
    assert any(text.startswith("09:00") and "10:00" in text for text in labels), labels
    assert "10:00 - 11:00" not in joined
    assert not view._error.isVisible()


def test_planner_no_free_slots_when_fully_booked(qapp, controller, tmp_path):
    app = QApplication.instance()
    tz = ZoneInfo("Asia/Kolkata")
    day = datetime(2026, 11, 11, tzinfo=tz)
    # Book the entire work day.
    _add_event(
        controller.conn,
        "All day",
        day.replace(hour=9).isoformat(),
        day.replace(hour=17).isoformat(),
    )
    view = PlannerView(controller)
    view._date.setText("2026-11-11")
    view._plan()
    app.processEvents()

    assert view._slots.count() == 0
    assert "No free slots" in view._status.text()
    assert not view._error.isVisible()
