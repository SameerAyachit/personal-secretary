"""Inbox view: history of notifications with statuses and transitions (plan §10.3).

Each row shows title/body plus Ack / Snooze / Done actions that transition the
inbox item status (unacknowledged -> acknowledged / snoozed / done).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from secretary.ui.widgets.empty_state import EmptyState


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

        self._list = QListWidget()
        layout.addWidget(self._list)

        self._empty = EmptyState("No unacknowledged inbox items.")
        self._empty.hide()
        layout.addWidget(self._empty)

        self._controller.inbox_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        try:
            rows = self._controller.list_inbox()
        except Exception:
            rows = []
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
            ack = QPushButton("Ack")
            ack.clicked.connect(lambda checked, iid=row["id"]: self._controller.ack_inbox(iid))
            snooze = QPushButton("Snooze")
            snooze.clicked.connect(lambda checked, iid=row["id"]: self._controller.snooze_inbox(iid, "10 minutes"))
            done = QPushButton("Done")
            done.setObjectName("Accent")
            done.clicked.connect(lambda checked, iid=row["id"]: self._controller.done_inbox(iid))
            row_layout.addStretch()
            row_layout.addWidget(ack)
            row_layout.addWidget(snooze)
            row_layout.addWidget(done)
            self._list.setItemWidget(item, row_widget)
