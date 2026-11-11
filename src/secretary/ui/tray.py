"""System tray icon: Open/Quit menu plus an inbox overflow hint (plan C-4).

The tray menu lists the most recent unacknowledged inbox items so they are
visible at a glance. When there are more than MAX_VISIBLE items, a disabled
"+N more" action hints that further items are hidden (Windows tray overflow)
and they are all shown in the Inbox view.

item_activated(title, body) is emitted when a tray menu item is chosen; the
window layer decides what to show (the Inbox view).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

MAX_VISIBLE = 5


class TrayIcon(QObject):
    """Wraps QSystemTrayIcon with an Open/Quit menu and an inbox overflow hint."""

    item_activated = Signal(str, str)  # title, body

    def __init__(self, window, controller) -> None:
        super().__init__()
        self._window = window
        self._controller = controller
        self._tray = QSystemTrayIcon()
        if QIcon.fromTheme("secretary").isNull():
            self._tray.setIcon(QIcon())  # fallback until packaging icons exist
        self._tray.setToolTip("Secretary")
        self._menu = QMenu()
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)
        self._tray.show()
        self.refresh()

    def tray_icon(self) -> QSystemTrayIcon:
        """Underlying QSystemTrayIcon, for the notifier's badge/tooltip."""
        return self._tray

    def setToolTip(self, text: str) -> None:
        self._tray.setToolTip(text)

    def refresh(self) -> None:
        """Rebuild the menu from the current unacknowledged inbox items."""
        self._menu.clear()
        items = self._controller.list_inbox_preview()
        count = len(items)
        overflow = max(0, count - MAX_VISIBLE)
        show = items[:MAX_VISIBLE]

        open_action = QAction("Open", parent=self._menu)
        open_action.triggered.connect(self._window.show_window)  # type: ignore[arg-type]
        self._menu.addAction(open_action)

        for item in show:
            title = item.get("title", "")
            body = item.get("body", "")
            display = title if len(title) <= 50 else title[:47] + "..."
            action = QAction(display.replace("&", "&&"), parent=self._menu)
            action.triggered.connect(  # type: ignore[arg-type]
                lambda checked=False, t=title, b=body: self._activate(t, b)
            )
            self._menu.addAction(action)

        if overflow:
            hint = QAction(f"+{overflow} more unread reminder(s)", parent=self._menu)
            hint.setEnabled(False)
            self._menu.addAction(hint)

        self._menu.addSeparator()
        quit_action = QAction("Quit", parent=self._menu)
        quit_action.triggered.connect(self._quit)  # type: ignore[arg-type]
        self._menu.addAction(quit_action)

        self._tray.setToolTip(f"Secretary ({count} unread)" if count else "Secretary")

    def _activate(self, title: str, body: str) -> None:
        self.item_activated.emit(title, body)
        self._window.show_window()

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._window.show_window()

    def _quit(self) -> None:
        # The controller owns the App; Quit is handled by the main loop.
        pass

    def show(self) -> None:
        self._tray.show()

    def hide(self) -> None:
        self._tray.hide()
