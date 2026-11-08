"""Approvals view shell: waiting class-C actions with code-built summaries,
Approve/Reject, expiry countdown (plan §12.2).
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


class ApprovalsView(QWidget):
    """Waiting class-C actions awaiting user approval."""

    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Approvals awaiting your decision"))
        self._list = QListWidget()
        layout.addWidget(self._list)

        self._controller.approvals_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self._list.clear()
        try:
            rows = self._controller.list_pending_actions()
        except Exception:
            rows = []
        for row in rows:
            item = QListWidgetItem(f"{row['summary']}\n{row['payload_json']}")
            item.setData(Qt.UserRole, row["id"])
            self._list.addItem(item)
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(4, 2, 4, 2)
            row_layout.addWidget(QLabel(row["status"]))
            approve = QPushButton("Approve")
            approve.clicked.connect(
                lambda checked, iid=row["id"]: self._controller.approve_action(iid)
            )
            reject = QPushButton("Reject")
            reject.clicked.connect(
                lambda checked, iid=row["id"]: self._controller.reject_action(iid)
            )
            row_layout.addStretch()
            row_layout.addWidget(approve)
            row_layout.addWidget(reject)
            self._list.setItemWidget(item, row_widget)
