"""Today view placeholder: unacknowledged reminders, approvals, quick-add, plan my day."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class TodayView(QWidget):
    """Placeholder Today view (fully wired in Phase 2)."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(QLabel("Today"))
        layout.addWidget(
            QLabel("Reminders, approvals and today's tasks appear here (wired in Phase 2).")
        )
        layout.addStretch()
