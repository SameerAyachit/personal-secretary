"""Empty state widget (plan §12, skill §3).

Shows a caption title and an optional primary action when a view has nothing
to display. Every data view should present an empty state instead of a bare
empty list.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class EmptyState(QWidget):
    def __init__(
        self,
        title: str,
        action_text: str | None = None,
        action=None,
    ) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(12)

        self._title = QLabel(title)
        self._title.setObjectName("Caption")
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setWordWrap(True)
        layout.addWidget(self._title)

        self._action = None
        if action_text and action is not None:
            self._action = QPushButton(action_text)
            self._action.setObjectName("Accent")
            self._action.clicked.connect(action)
            layout.addWidget(self._action, alignment=Qt.AlignCenter)
