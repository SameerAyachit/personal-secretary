"""Tests for the tray overflow hint (plan C-4).

The tray menu lists recent unacknowledged inbox items; when there are more
than MAX_VISIBLE, a disabled "+N more" action hints that the rest are hidden
in the Windows tray overflow and shown in the Inbox view.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from secretary.ui.tray import TrayIcon


class _FakeController:
    def __init__(self, items) -> None:
        self._items = list(items)

    def list_inbox_preview(self, limit: int | None = None) -> list[dict]:
        return self._items if limit is None else self._items[:limit]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _item_titles(menu) -> list[str]:
    return [action.text() for a in menu.actions() for action in [a] if not a.isSeparator()]


def test_tray_menu_lists_inbox_items_with_overflow_hint(qapp):
    items = [
        {"title": f"Reminder {i}", "body": f"body {i}"} for i in range(7)
    ]
    controller = _FakeController(items)
    window = MagicMock()
    tray = TrayIcon(window, controller)

    titles = _item_titles(tray._menu)
    assert "Open" in titles
    assert "Quit" in titles
    shown = [t for t in titles if t.startswith("Reminder")]
    assert shown == ["Reminder 0", "Reminder 1", "Reminder 2", "Reminder 3", "Reminder 4"]
    assert any("+2 more unread reminder(s)" in t for t in titles)
    assert "7 unread" in tray._tray.toolTip()


def test_tray_no_overflow_hint_when_few_items(qapp):
    controller = _FakeController([{"title": "One", "body": "b"}])
    window = MagicMock()
    tray = TrayIcon(window, controller)
    titles = _item_titles(tray._menu)
    assert not any("more" in t for t in titles)
    assert "1 unread" in tray._tray.toolTip()


def test_tray_item_activation_shows_window(qapp):
    controller = _FakeController([{"title": "Drink water", "body": "body"}])
    window = MagicMock()
    tray = TrayIcon(window, controller)
    activated: list[tuple[str, str]] = []
    tray.item_activated.connect(lambda t, b: activated.append((t, b)))
    item = next(a for a in tray._menu.actions() if a.text() == "Drink water")
    item.trigger()
    assert activated == [("Drink water", "body")]
    window.show_window.assert_called()


def test_tray_empty_inbox(qapp):
    controller = _FakeController([])
    window = MagicMock()
    tray = TrayIcon(window, controller)
    titles = _item_titles(tray._menu)
    assert titles == ["Open", "Quit"]
    assert tray._tray.toolTip() == "Secretary"
