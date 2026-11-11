"""Planner view: code-assisted day planning (plan C-54).

``plan_day`` runs on the worker loop via the controller and returns the day's
free slots (9:00-17:00 local, around calendar events). The view displays them
and lets the user create a task in a chosen slot. All date computation is done
in code (plan_day), never by the LLM -- the LLM only phrases.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from secretary.controller import Controller


def _today_iso(tz_name: str = "Asia/Kolkata") -> str:
    return datetime.now(UTC).astimezone(ZoneInfo(tz_name)).date().isoformat()


class PlannerView(QWidget):
    """Show free slots for a day and create tasks in them."""

    def __init__(self, controller: Controller) -> None:
        super().__init__()
        self._controller = controller
        self._tz = "Asia/Kolkata"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Planner")
        title.setObjectName("Section")
        layout.addWidget(title)

        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("Date"))
        self._date = QLineEdit(_today_iso(self._tz))
        self._date.setPlaceholderText("YYYY-MM-DD")
        self._date.returnPressed.connect(self._plan)
        date_row.addWidget(self._date)
        plan_btn = QPushButton("Plan day")
        plan_btn.setObjectName("Accent")
        plan_btn.clicked.connect(self._plan)
        date_row.addWidget(plan_btn)
        layout.addLayout(date_row)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #5B6573; font-size: 12px;")
        self._status.setHidden(True)
        layout.addWidget(self._status)

        self._slots = QListWidget()
        self._slots.setAlternatingRowColors(True)
        layout.addWidget(self._slots)

        self._error = QLabel("")
        self._error.setStyleSheet("color: #C62828; font-size: 12px;")
        self._error.setHidden(True)
        layout.addWidget(self._error)

        # Create-task row (revealed when free slots exist).
        self._create_row = QHBoxLayout()
        self._create_row.addWidget(QLabel("Create task in slot:"))
        self._task_input = QLineEdit()
        self._task_input.setPlaceholderText("Task title")
        self._create_row.addWidget(self._task_input)
        self._create_btn = QPushButton("Create task")
        self._create_btn.setObjectName("Accent")
        self._create_btn.clicked.connect(self._create_task)
        self._create_row.addWidget(self._create_btn)
        self._create_row_widget = QWidget()
        self._create_row_widget.setLayout(self._create_row)
        self._create_row_widget.setHidden(True)
        layout.addWidget(self._create_row_widget)

        layout.addStretch()

    @Slot()
    def _plan(self) -> None:
        self._slots.clear()
        self._error.setHidden(True)
        self._status.setHidden(True)
        self._create_row_widget.setHidden(True)
        date_iso = self._date.text().strip() or _today_iso(self._tz)
        try:
            result = self._controller.get_free_slots(date_iso, self._tz)
        except Exception as exc:  # surface to UI
            self._error.setText(f"Planning failed: {exc}")
            self._error.setHidden(False)
            return
        free_slots = result.get("free_slots", []) or []
        if not free_slots:
            self._status.setText(f"No free slots on {result.get('date', date_iso)}.")
            self._status.setHidden(False)
            return
        for slot in free_slots:
            start = slot["start"]
            end = slot["end"]
            try:
                start_local = datetime.fromisoformat(start).astimezone(ZoneInfo(self._tz))
                end_local = datetime.fromisoformat(end).astimezone(ZoneInfo(self._tz))
                label = f"{start_local:%H:%M} - {end_local:%H:%M}"
            except Exception:
                label = f"{start} - {end}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, slot)
            self._slots.addItem(item)
        self._create_row_widget.setHidden(False)
        self._status.setText(f"{len(free_slots)} free slot(s) on {result.get('date', date_iso)}.")
        self._status.setHidden(False)

    @Slot()
    def _create_task(self) -> None:
        item = self._slots.currentItem()
        if item is None:
            self._error.setText("Select a free slot first.")
            self._error.setHidden(False)
            return
        title = self._task_input.text().strip()
        if not title:
            self._error.setText("Enter a task title.")
            self._error.setHidden(False)
            return
        slot = item.data(Qt.UserRole)
        self._controller.create_task_at(title, slot["start"], self._tz)
        self._task_input.clear()
        self._status.setText(f"Task created: {title}")
        self._status.setHidden(False)
