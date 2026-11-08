"""Quick-capture window: small centered input, Enter sends to the agent, Esc closes
(plan §12.3).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget


class QuickCapture(QWidget):
    """Centered quick-capture input shown when the global hotkey fires."""

    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Quick capture...")
        self._input.returnPressed.connect(self._send)
        layout.addWidget(self._input)

        btn_row = QHBoxLayout()
        send_btn = QPushButton("Send")
        send_btn.setObjectName("Accent")
        send_btn.clicked.connect(self._send)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.hide)
        btn_row.addStretch()
        btn_row.addWidget(send_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._center()
        self._input.setFocus()

    def _center(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        fg = self.frameGeometry()
        fg.moveCenter(geo.center())
        self.move(fg.topLeft())

    def _send(self) -> None:
        text = self._input.text().strip()
        if text:
            self._controller.send_message(text)
            self._input.clear()
        self.hide()

    def show_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)
