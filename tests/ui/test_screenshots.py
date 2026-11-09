"""Screenshot grabs for the UI review loop (plan §12, skill secretary-ui-design §7).

Grabs the Settings view in light and dark themes (offscreen QT_QPA_PLATFORM)
and saves PNGs under docs/screenshots/. Also runs the programmatic checks the
skill requires when images cannot be inspected directly: labels non-empty and
a cycling tab order.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtWidgets import QApplication, QWidget

from secretary.controller import Controller
from secretary.ui.theme import apply_theme
from secretary.ui.views.settings import SettingsView

OUT = Path("docs/screenshots")


class _DummyConn:
    """Controller only stores the connection; autostart only reads the Run key."""


def _grab(app: QApplication, theme: str, name: str) -> QWidget:
    apply_theme(app, theme)
    view = SettingsView(Controller(_DummyConn()))
    view.resize(900, 600)
    view.show()
    pix = view.grab()
    path = OUT / f"settings_{theme}_{name}.png"
    assert pix.save(str(path))
    return view


def test_settings_screenshots_and_checks() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    views: list[QWidget] = []
    for theme, scale in (("light", "100"), ("dark", "100")):
        views.append(_grab(app, theme, scale))
        path = OUT / f"settings_{theme}_{scale}.png"
        assert path.exists() and path.stat().st_size > 0

    # Programmatic checks (skill §7: no widget sizeHint exceeds its size,
    # no empty label text, tab order cycles).
    view = views[-1]
    for widget in view.findChildren(QWidget):
        hint = widget.sizeHint()
        assert hint.isValid(), f"invalid sizeHint: {widget}"
        if not widget.isHidden():
            size = widget.size()
            assert size.isValid() and size.width() > 0 and size.height() > 0
            assert hint.width() <= size.width() and hint.height() <= size.height(), (
                f"sizeHint exceeds size: {widget}"
            )
        if widget.inherits("QLabel") and not widget.text():
            raise AssertionError(f"empty label text: {widget}")

    first = view._autostart
    assert first.focusPolicy() & 1  # TabFocus
    current = first
    steps = 0
    while True:
        current = current.nextInFocusChain()
        steps += 1
        assert steps < 50, "tab order chain does not cycle"
        if current is first:
            break
