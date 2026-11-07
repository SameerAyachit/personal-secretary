"""Main window: hide/show, minimize-to-tray, never exit on close (plan §3.1, C-3)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow


class MainWindow(QMainWindow):
    """The single Secretary window. Closing hides it; tray Quit is the only exit."""

    def __init__(self, app) -> None:
        super().__init__()
        self._app = app
        self.setWindowTitle("Secretary")
        self.setMinimumSize(900, 600)

    def hide_to_tray(self) -> None:
        self.hide()

    def show_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        # Reminders must keep firing: never quit when the window closes.
        event.ignore()
        self.hide()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)
