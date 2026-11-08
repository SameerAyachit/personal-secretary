"""Events view: calendar events in a time-ordered list (plan §13)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget


class EventsView(QWidget):
    """Lists calendar events in time order."""

    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Calendar events"))
        self._list = QListWidget()
        layout.addWidget(self._list)

        self._controller.tasks_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self._list.clear()
        try:
            events = self._controller.list_events()
        except Exception:
            events = []
        for ev in events:
            item = QListWidgetItem(f"{ev['start_at']} — {ev['title']}")
            item.setData(Qt.UserRole, ev["id"])
            self._list.addItem(item)
