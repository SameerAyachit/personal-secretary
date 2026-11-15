"""Inbox view: history of notifications with statuses and transitions (plan §10.3).

A filter bar (New / Snoozed / Acknowledged / Done / All) chooses what is listed.
Each row offers every action except the one matching its current status, plus
Reopen once it has left New, so a choice can always be changed.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from secretary.ui.widgets.empty_state import EmptyState

_FILTERS: tuple[tuple[str, str | None, str], ...] = (
    ("unacknowledged", "unacknowledged", "New"),
    ("snoozed", "snoozed", "Snoozed"),
    ("acknowledged", "acknowledged", "Acknowledged"),
    ("done", "done", "Done"),
    ("all", None, "All"),
)
_EMPTY_TEXT = {
    "unacknowledged": "No unacknowledged inbox items.",
    "snoozed": "No snoozed inbox items.",
    "acknowledged": "No acknowledged inbox items.",
    "done": "No inbox items marked done.",
    "all": "The inbox is empty.",
}
_SNOOZE_CHOICES = ("10 minutes", "1 hour", "Tomorrow 9am")


class InboxView(QWidget):
    """Lists inbox items and lets the user acknowledge, snooze or done them."""

    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self._label = QLabel("Inbox")
        self._label.setObjectName("Section")
        layout.addWidget(self._label)

        self._filter_key = "unacknowledged"
        self._filter_buttons: dict[str, QPushButton] = {}
        filter_bar = QHBoxLayout()
        for key, _status, text in _FILTERS:
            button = QPushButton(text)
            button.setCheckable(True)
            button.setChecked(key == self._filter_key)
            button.setAccessibleName(f"Show {text} inbox items")
            button.clicked.connect(lambda checked=False, k=key: self._set_filter(k))
            self._filter_buttons[key] = button
            filter_bar.addWidget(button)
        filter_bar.addStretch()
        layout.addLayout(filter_bar)

        self._list = QListWidget()
        layout.addWidget(self._list)

        self._empty = EmptyState(_EMPTY_TEXT[self._filter_key])
        self._empty.hide()
        layout.addWidget(self._empty)

        self._controller.inbox_changed.connect(self.refresh)
        self.refresh()

    def _set_filter(self, key: str) -> None:
        self._filter_key = key
        for name, button in self._filter_buttons.items():
            button.setChecked(name == key)
        self.refresh()

    def refresh(self) -> None:
        status_filter = next(s for k, s, _t in _FILTERS if k == self._filter_key)
        try:
            rows = self._controller.list_inbox(status_filter)
        except Exception:
            rows = []
        self._empty._title.setText(_EMPTY_TEXT[self._filter_key])
        has_rows = bool(rows)
        self._list.setVisible(has_rows)
        self._empty.setVisible(not has_rows)
        self._list.clear()
        for row in rows:
            item = QListWidgetItem(f"{row['title']}\n{row['body']}")
            item.setData(Qt.UserRole, row["id"])
            status = row["status"] or "unacknowledged"
            item.setToolTip(f"Status: {status}")
            self._list.addItem(item)

            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(4, 2, 4, 2)
            row_layout.addWidget(QLabel(status))
            row_layout.addStretch()
            iid = row["id"]
            if status != "unacknowledged":
                reopen = QPushButton("Reopen")
                reopen.clicked.connect(lambda checked=False, i=iid: self._controller.reopen_inbox(i))
                row_layout.addWidget(reopen)
            if status != "acknowledged":
                ack = QPushButton("Ack")
                ack.clicked.connect(lambda checked=False, i=iid: self._controller.ack_inbox(i))
                row_layout.addWidget(ack)
            snooze = QPushButton("Snooze")
            menu = QMenu(snooze)
            for choice in _SNOOZE_CHOICES:
                action = menu.addAction(choice)
                action.triggered.connect(
                    lambda checked=False, i=iid, c=choice: self._controller.snooze_inbox(i, c.lower())
                )
            snooze.setMenu(menu)
            row_layout.addWidget(snooze)
            if status != "done":
                done = QPushButton("Done")
                done.setObjectName("Accent")
                done.clicked.connect(lambda checked=False, i=iid: self._controller.done_inbox(i))
                row_layout.addWidget(done)
            self._list.setItemWidget(item, row_widget)
