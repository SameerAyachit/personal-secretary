"""Chat view screenshot / no-clip checks (secretary-ui-design skill §7).

Renders the chat view at 900x600 and 1400x900 in light and dark, adds long
user / assistant / error messages, and asserts no message bubble is clipped:
each bubble's sizeHint width must be <= the viewport width (text wraps instead
of overflowing). Also verifies bubble alignment (user right, assistant/error
left) and that error bubbles carry a danger-coloured left border.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication, QFrame

from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.ui.theme import apply_theme
from secretary.ui.views.chat import ChatView

OUT = Path("docs/screenshots")


class _DummyConn:
    """Controller only stores the connection."""


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "chat.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con, migrations_folder(), lambda: None)
    return con


def _add_messages(view: ChatView) -> None:
    view._add_user("hey, remind me to drink water in 1 minute please")
    view._add_assistant(
        "I've set a reminder to drink water in 20 seconds. It will appear in your inbox when it fires."
    )
    view._add_message(
        "Secretary:",
        "I hit an error: provider returned 400: {\"error\":{\"message\":\"messages.2.tool_calls.0.type: property 'type' is missing\",\"type\":\"invalid_request_error\"}}",
        "error",
        technical="provider returned 400: {\"error\":{\"message\":\"messages.2.tool_calls.0.type: property 'type' is missing\",\"type\":\"invalid_request_error\"}}",
    )


def _bubbles(view: ChatView):
    return [
        w
        for w in view._container.findChildren(QFrame)
        if w.objectName() == "ChatBubble"
    ]


def _test_size(app: QApplication, view: ChatView, size: tuple[int, int], theme: str) -> None:
    apply_theme(app, theme)
    view.resize(size[0], size[1])
    view.show()
    app.processEvents()
    viewport_w = view._scroll.viewport().width()
    _add_messages(view)
    app.processEvents()
    assert _bubbles(view), "no chat bubbles rendered"
    for bubble in _bubbles(view):
        sh = bubble.sizeHint()
        assert sh.width() <= viewport_w, (
            f"bubble clipped: sizeHint width {sh.width()} > viewport {viewport_w} "
            f"({size[0]}x{size[1]} {theme})"
        )
        assert bubble.maximumWidth() <= viewport_w, (
            f"bubble maxWidth {bubble.maximumWidth()} > viewport {viewport_w}"
        )
        assert bubble.layout() is not None
    OUT.mkdir(parents=True, exist_ok=True)
    pix = view.grab()
    assert pix.save(str(OUT / f"chat_{size[0]}x{size[1]}_{theme}.png"))


def test_chat_no_clip_at_sizes_and_themes() -> None:
    app = QApplication.instance() or QApplication([])
    for size in ((900, 600), (1400, 900)):
        for theme in ("light", "dark"):
            view = ChatView(Controller(_DummyConn()))
            _test_size(app, view, size, theme)
            # Alignment: user bubble right, assistant/error left.
            bubbles = _bubbles(view)
            assert len(bubbles) == 3
            user = bubbles[0]
            assistant = bubbles[1]
            error = bubbles[2]
            assert user.property("kind") == "user"
            assert assistant.property("kind") == "assistant"
            assert error.property("kind") == "error"
            # Alignment: user right, assistant/error left (view coords).
            def right_edge(w, view=view):
                return w.mapTo(view, w.rect().bottomRight()).x()
            def left_edge(w, view=view):
                return w.mapTo(view, w.rect().topLeft()).x()
            assert right_edge(user) >= view.width() - 140, "user bubble not right-aligned"
            assert left_edge(assistant) <= 140, "assistant bubble not left-aligned"
            assert left_edge(error) <= 140, "error bubble not left-aligned"
            # Error bubble carries the danger left border.
            style = error.styleSheet()
            assert "border-left" in style and ("#c62828" in style.lower() or "#ff6b6b" in style.lower()), style


def test_send_disabled_while_turn_runs_and_errors_styled():
    app = QApplication.instance() or QApplication([])
    controller = Controller(_conn())
    controller.send_message = lambda text, priority="interactive": None  # no LLM
    view = ChatView(controller)
    view._input.setText("remind me to drink water in 10 minutes")
    view._on_send()
    assert not view._send_btn.isEnabled()
    controller.turn_finished.emit("I hit an error: provider returned 401: bad key")
    app.processEvents()
    assert view._send_btn.isEnabled()
    assert any(b.property("kind") == "error" for b in _bubbles(view))
