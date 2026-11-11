"""Popup reminder card: frameless, always-on-top, bottom-right (plan §10-11, C-6).

A spike implementation for P0-04. The real reminder wiring is added in Phase 2.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class PopupCard(QWidget):
    """A frameless, always-on-top reminder card shown bottom-right of the primary screen.

    Emits ``snooze`` and ``done`` so the controller can act on them. Auto-closes
    after ``AUTO_CLOSE_SECONDS`` so a card never lingers forever. Multiple cards
    stack vertically (each new one appears below the previous).
    """

    snooze = Signal()
    done = Signal()

    AUTO_CLOSE_SECONDS = 300
    _stack_offset = 0  # shared counter so multiple cards stack vertically

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
        self._snooze_btn = QPushButton("Snooze")
        self._done_btn = QPushButton("Done")
        self._snooze_btn.clicked.connect(self.snooze.emit)
        self._done_btn.clicked.connect(self.done.emit)
        bar.addWidget(self._snooze_btn)
        bar.addWidget(self._done_btn)
        bar.addStretch()
        layout.addLayout(bar)

        self.resize(self.sizeHint())

        # Auto-close after AUTO_CLOSE_SECONDS so a card never lingers forever.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.close_popup)
        self._timer.start(self.AUTO_CLOSE_SECONDS * 1000)

    def show_popup(self) -> None:
        """Show the card, stacking below any already-visible cards."""
        PopupCard._stack_offset += 1
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else self.geometry()
        card_w = self.width()
        card_h = self.height()
        # Stack cards vertically: each new card appears above the previous one.
        x = geo.right() - card_w - 16
        y = geo.bottom() - card_h - 16 - (PopupCard._stack_offset * (card_h + 12))
        self.move(QPoint(x, y))
        self.show()

    def close_popup(self) -> None:
        PopupCard._stack_offset = max(0, PopupCard._stack_offset - 1)
        self.close()

    def closeEvent(self, event):  # type: ignore[override]
        PopupCard._stack_offset = max(0, PopupCard._stack_offset - 1)
        super().closeEvent(event)
