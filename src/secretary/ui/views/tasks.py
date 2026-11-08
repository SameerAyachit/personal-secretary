"""Tasks view: task list with manual quick-add that works without the LLM."""

from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


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

        add_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Quick-add a task (e.g. \"buy groceries\")")
        self._input.returnPressed.connect(self._on_add)
        add_btn = QPushButton("Add")
        add_btn.setObjectName("Accent")
        add_btn.clicked.connect(self._on_add)
        add_row.addWidget(self._input)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        self._controller.tasks_changed.connect(self.refresh)
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        self._list.clear()
        try:
            rows = self._controller.list_tasks()
            for row in rows:
                item = QListWidgetItem(row["title"])
                item.setData(Qt.UserRole, row["id"])
                self._list.addItem(item)
        except Exception:
            pass

    @Slot()
    def _on_add(self) -> None:
        title = self._input.text().strip()
        if not title:
            return
        self._controller.create_task_manual(title, "")
        self._input.clear()
        self.refresh()
