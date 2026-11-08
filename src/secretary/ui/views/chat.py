"""Chat view: message list with a send field (no LLM wired yet)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ChatView(QWidget):
    """Simple chat transcript. Without an LLM, sends are acknowledged."""

    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        layout.addWidget(self._list)

        intro = QListWidgetItem("Secretary is ready. Type a message or use the quick-add field to create a task.")
        intro.setForeground(Qt.GlobalColor.gray)
        self._list.addItem(intro)

        send_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a message...")
        self._input.returnPressed.connect(self._on_send)
        send_btn = QPushButton("Send")
        send_btn.setObjectName("Accent")
        send_btn.clicked.connect(self._on_send)
        send_row.addWidget(self._input)
        send_row.addWidget(send_btn)
        layout.addLayout(send_row)

        self._controller.turn_finished.connect(self._on_turn_finished)

    @Slot(str)
    def _on_turn_finished(self, text: str) -> None:
        if text:
            self._add_assistant(text)

    @Slot()
    def _on_send(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._add_user(text)
        self._input.clear()
        self._controller.send_message(text)

    def _add_user(self, text: str) -> None:
        item = QListWidgetItem(f"You: {text}")
        item.setForeground(Qt.GlobalColor.black)
        self._list.addItem(item)
        self._list.scrollToBottom()

    def _add_assistant(self, text: str) -> None:
        item = QListWidgetItem(f"Secretary: {text}")
        item.setForeground(Qt.GlobalColor.darkGray)
        self._list.addItem(item)
        self._list.scrollToBottom()
