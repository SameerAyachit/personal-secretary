"""Popup reminder card: frameless, always-on-top, bottom-right (plan §10-11, C-6).

A spike implementation for P0-04. The real reminder wiring is added in Phase 2.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class PopupCard(QWidget):
    """A frameless, always-on-top reminder card shown bottom-right of the primary screen."""

    def __init__(self, title: str = "Reminder", body: str = "") -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # no focus steal

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._title = QLabel(title)
        self._body = QLabel(body)
        self._title.setStyleSheet("font-weight: 600; font-size: 13px;")
        self._body.setStyleSheet("font-size: 12px;")
        layout.addWidget(self._title)
        layout.addWidget(self._body)

        bar = QHBoxLayout()
        self._snooze = QPushButton("Snooze")
        self._done = QPushButton("Done")
        bar.addWidget(self._snooze)
        bar.addWidget(self._done)
        bar.addStretch()
        layout.addLayout(bar)

        self.resize(self.sizeHint())

    def show_popup(self) -> None:
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else self.geometry()
        x = geo.right() - self.width() - 16
        y = geo.bottom() - self.height() - 16
        self.move(QPoint(x, y))
        self.show()

    def close_popup(self) -> None:
        self.close()
