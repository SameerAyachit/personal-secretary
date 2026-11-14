"""Events view: calendar events in a time-ordered list (plan §13)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from secretary.ui.widgets.empty_state import EmptyState


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

        self._empty = EmptyState("No upcoming events.")
        self._empty.hide()
        layout.addWidget(self._empty)

        self._controller.tasks_changed.connect(self.refresh)
        self._controller.events_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        try:
            events = self._controller.list_events()
        except Exception:
            events = []
        has_rows = bool(events)
        self._list.setVisible(has_rows)
        self._empty.setVisible(not has_rows)
        self._list.clear()
        for ev in events:
            item = QListWidgetItem(f"{ev['start_at']} — {ev['title']}")
            item.setData(Qt.UserRole, ev["id"])
            self._list.addItem(item)
