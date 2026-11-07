"""System tray icon: Open / Quit menu, single-instance raise target."""

from __future__ import annotations

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class TrayIcon:
    """Wraps QSystemTrayIcon with an Open/Quit context menu."""

    def __init__(self, app, main_window) -> None:
        self._tray = QSystemTrayIcon()
        self._tray.setToolTip("Secretary")
        if QIcon.fromTheme("secretary").isNull():
            self._tray.setIcon(QIcon())  # fallback until packaging icons exist
        self._menu = QMenu()
        open_action = QAction("Open", main_window)
        open_action.triggered.connect(main_window.show_window)
        quit_action = QAction("Quit", main_window)
        quit_action.triggered.connect(self._quit)
        self._menu.addAction(open_action)
        self._menu.addSeparator()
        self._menu.addAction(quit_action)
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)
        self._tray.show()

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._main_window_show()

    def _main_window_show(self) -> None:
        pass  # wired by the controller once it exists

    def _quit(self) -> None:
        # The controller owns the App; Quit is handled by the main loop.
        pass

    def show(self) -> None:
        self._tray.show()

    def hide(self) -> None:
        self._tray.hide()
