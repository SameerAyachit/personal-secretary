"""Tasks view: task list with manual quick-add that works without the LLM."""

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


class TasksView(QWidget):
    """Lists open tasks and offers a manual quick-add field."""

    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        layout.addWidget(self._list)

        self._empty = EmptyState("No tasks yet.", "Add a task", self._input_focus)
        self._empty.hide()
        layout.addWidget(self._empty)

        add_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText(
            "Task or reminder (e.g. \"buy groceries\" / \"remind me to call at 5pm\")"
        )
        self._input.returnPressed.connect(self._on_add)
        add_btn = QPushButton("Add")
        add_btn.setObjectName("Accent")
        add_btn.clicked.connect(self._on_add)
        add_row.addWidget(self._input)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #5B6573; font-size: 12px;")
        self._status.setHidden(True)
        layout.addWidget(self._status)

        self._controller.tasks_changed.connect(self.refresh)
        self.refresh()

    def _input_focus(self) -> None:
        self._input.setFocus()

    @Slot()
    def refresh(self) -> None:
        try:
            rows = self._controller.list_tasks()
        except Exception:
            rows = []
        has_rows = bool(rows)
        self._list.setVisible(has_rows)
        self._empty.setVisible(not has_rows)
        self._list.clear()
        for row in rows:
            item = QListWidgetItem(row["title"])
            item.setData(Qt.UserRole, row["id"])
            self._list.addItem(item)

    @Slot()
    def _on_add(self) -> None:
        title = self._input.text().strip()
        if not title:
            return
        if "remind" in title.lower():
            self._controller.create_reminder_manual(title, "")
            self._status.setText(f"Reminder created: {title}")
        else:
            self._controller.create_task_manual(title, "")
            self._status.setText(f"Task created: {title}")
        self._status.setHidden(False)
        self._input.clear()
        self.refresh()
