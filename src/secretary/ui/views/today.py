"""Today view: unacknowledged reminders (top, with Snooze/Done), approvals waiting,
"While you were away" card, today's events and due tasks in time order, a quick-add
field, and a "Plan my day" button (plan §12.2).
"""

from __future__ import annotations

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

from secretary.ui.widgets.empty_state import EmptyState


class TodayView(QWidget):
    """Today's reminders, approvals, "while you were away" card, due tasks, quick-add."""

    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Quick-add.
        add_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Quick-add a task or reminder")
        self._input.returnPressed.connect(self._on_add)
        add_btn = QPushButton("Add")
        add_btn.setObjectName("Accent")
        add_btn.clicked.connect(self._on_add)
        add_row.addWidget(self._input)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        plan_btn = QPushButton("Plan my day")
        plan_btn.clicked.connect(self._on_plan)
        layout.addWidget(plan_btn)

        # Reminders section.
        layout.addWidget(QLabel("Reminders"))
        self._reminders_list = QListWidget()
        layout.addWidget(self._reminders_list)

        self._reminders_empty = EmptyState("No unacknowledged reminders.")
        self._reminders_empty.hide()
        layout.addWidget(self._reminders_empty)

        # While you were away card.
        self._away_card = QLabel()
        self._away_card.setObjectName("Card")
        self._away_card.setWordWrap(True)
        self._away_card.setVisible(False)
        layout.addWidget(self._away_card)

        self._controller.tasks_changed.connect(self.refresh)
        self._controller.inbox_changed.connect(self.refresh)
        self.refresh()
    def refresh(self) -> None:
        try:
            inbox = self._controller.list_inbox()
        except Exception:
            inbox = []
        try:
            tasks = self._controller.list_tasks()
        except Exception:
            tasks = []

        # Reminders (unacknowledged).
        reminders = [r for r in inbox if r.get("kind") == "reminder"]
        has_reminders = bool(reminders)
        self._reminders_list.setVisible(has_reminders)
        self._reminders_empty.setVisible(not has_reminders)
        self._reminders_list.clear()
        for r in reminders:
            item = QListWidgetItem(f"{r['title']} — {r['body']}")
            item.setData(Qt.UserRole, r["id"])
            self._reminders_list.addItem(item)

        # While you were away card.
        aways = [r for r in inbox if r.get("kind") == "while_away"]
        if aways:
            self._away_card.setText(aways[0]["body"])
            self._away_card.setVisible(True)
        else:
            self._away_card.setVisible(False)

        # Tasks count.
        self._tasks_count = len(tasks)

    @Slot()
    def _on_add(self) -> None:
        title = self._input.text().strip()
        if not title:
            return
        self._controller.create_task_manual(title, "")
        self._input.clear()
        self.refresh()

    @Slot()
    def _on_plan(self) -> None:
        # "Plan my day": placeholder — full planner in Phase 3.
        pass
