"""Chat view: message list with a send field (plan §12, secretary-ui-design skill).

Message bubbles:
  * word-wrap at every window width (no horizontal clipping),
  * user messages right-aligned in the accent colour,
  * assistant messages left-aligned on surface_alt,
  * error messages left-aligned with a danger-coloured left border, short plain
    language, and the technical provider text collapsed behind a "Details"
    toggle,
  * nothing shares the sidebar's selected-item style (the list shows no
    selection).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from secretary.ui.theme import resolve_theme, tokens

_MAX_BUBBLE_WIDTH_RATIO = 0.66


def _current_palette(controller) -> object:
    """Resolve the active theme's palette for bubble colours."""
    theme = resolve_theme(controller.get_config().get("theme", "light"))
    return tokens(theme).palette


class _ChatBubble(QFrame):
    """A single chat message bubble."""

    def __init__(self, kind: str, text: str, technical: str | None, palette) -> None:
        super().__init__()
        self.setObjectName("ChatBubble")
        self.setProperty("kind", kind)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Short, user-facing text.
        short = text if kind != "error" else _short_error(text)
        self._label = QLabel(short)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(
            self._label.textInteractionFlags() | Qt.TextSelectableByMouse
        )
        layout.addWidget(self._label)

        # Technical detail collapsed behind a "Details" toggle.
        self._detail = None
        if technical:
            self._detail = QLabel(technical)
            self._detail.setWordWrap(True)
            self._detail.setObjectName("Caption")
            self._detail.setVisible(False)
            layout.addWidget(self._detail)
            btn = QPushButton("Details")
            btn.setFlat(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(self._toggle_detail)
            layout.addWidget(btn)

        self._apply_style(palette, kind)

    def _toggle_detail(self) -> None:
        if self._detail is None:
            return
        visible = not self._detail.isVisible()
        self._detail.setVisible(visible)
        self.adjustSize()

    def _apply_style(self, palette, kind: str) -> None:
        radius = 10
        if kind == "user":
            bg = palette.accent
            fg = palette.accent_text
        elif kind == "error":
            bg = palette.surface
            fg = palette.text
        else:  # assistant
            bg = palette.surface_alt
            fg = palette.text
        self.setStyleSheet(
            f"QFrame#ChatBubble {{ background-color: {bg}; color: {fg}; "
            f"border-radius: {radius}px; }}"
            + (f"QFrame#ChatBubble[kind=\"error\"] {{ border-left: 6px solid {palette.danger}; }}"
               if kind == "error"
               else "")
        )


def _short_error(text: str) -> str:
    """Plain-language short form of an error message."""
    prefix = "I hit an error: "
    if text.startswith(prefix):
        text = text[len(prefix):]
    # Keep only the first sentence / clause so it stays short.
    for sep in (". ", ":\n", "\n"):
        if sep in text:
            text = text.split(sep, 1)[0]
    return text.strip() or text


class ChatView(QWidget):
    """Chat transcript: message bubbles with a send field."""

    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller
        self._palette = _current_palette(controller)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Scrollable message area (no selection: bubbles never share the
        # sidebar's selected-item style).
        self._scroll = QScrollArea()
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setAlignment(Qt.AlignTop)
        self._container_layout.setSpacing(10)
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll)

        intro = QLabel("Secretary is ready. Type a message or use the quick-add field to create a task.")
        intro.setWordWrap(True)
        intro.setObjectName("Caption")
        self._container_layout.addWidget(intro)

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
        self._controller.error.connect(self._on_controller_error)

    # ------------------------------------------------------------------ messages

    def _add_message(self, prefix: str, text: str, kind: str, technical: str | None = None) -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        full_text = f"{prefix} {text}" if prefix else text
        bubble = _ChatBubble(kind, full_text, technical, self._palette)
        # Cap bubble width so text wraps at every window width and never clips.
        bubble.setMaximumWidth(int(self._scroll.viewport().width() * _MAX_BUBBLE_WIDTH_RATIO) or 520)

        if kind == "user":
            row_layout.addSpacerItem(QSpacerItem(20, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))
            row_layout.addWidget(bubble)
        else:
            row_layout.addWidget(bubble)
            row_layout.addSpacerItem(QSpacerItem(20, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self._container_layout.addWidget(row)
        self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum())

    def _add_user(self, text: str) -> None:
        self._add_message("You:", text, "user")

    def _add_assistant(self, text: str) -> None:
        self._add_message("Secretary:", text, "assistant")

    # ------------------------------------------------------------------ slots

    @Slot(str)
    def _on_turn_finished(self, text: str) -> None:
        if text:
            self._add_assistant(text)

    @Slot(str, str)
    def _on_controller_error(self, action: str, message: str) -> None:
        # Short plain-language text; technical provider text behind Details.
        self._add_message("Secretary:", message, "error", technical=message)

    @Slot()
    def _on_send(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._add_user(text)
        self._input.clear()
        self._controller.send_message(text)
