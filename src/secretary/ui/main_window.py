"""Main window: left-rail navigation + stacked content, hide-to-tray (plan §12.1, C-3)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QSystemTrayIcon,
    QWidget,
)

from secretary.controller import Controller
from secretary.ui.theme import apply_theme
from secretary.ui.views import approvals, chat, events, inbox, settings, tasks, today


def _effective_theme(stored: str) -> str:
    """Resolve the stored theme ("system" follows the Windows color scheme)."""
    if stored != "system":
        return stored
    scheme = QGuiApplication.styleHints().colorScheme()
    return "dark" if scheme == Qt.ColorScheme.Dark else "light"


class MainWindow(QMainWindow):
    """Single Secretary window. Closing hides to tray; tray Quit is the only exit."""

    def __init__(self, controller: Controller) -> None:
        super().__init__()
        self._controller = controller
        self.setWindowTitle("Secretary")
        self.setMinimumSize(900, 600)

        stored = self._controller.get_config().get("theme", "light")
        apply_theme(self, _effective_theme(stored))

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Left rail.
        self._rail = QListWidget()
        self._rail.setFixedWidth(200)
        self._rail.setFrameStyle(0)  # no frame
        for label in ("Today", "Chat", "Tasks", "Calendar", "Inbox", "Approvals", "Settings"):
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, label)
            self._rail.addItem(item)
        self._rail.setCurrentRow(0)
        self._rail.currentItemChanged.connect(self._on_rail_changed)
        root.addWidget(self._rail)

        # Content area.
        self._stack = QStackedWidget()

        self._tray = QSystemTrayIcon(self)
        self._tray.setToolTip("Secretary")

        self._views = {
            "Today": today.TodayView(controller),
            "Chat": chat.ChatView(controller),
            "Tasks": tasks.TasksView(controller),
            "Calendar": events.EventsView(controller),
            "Inbox": inbox.InboxView(controller),
            "Approvals": approvals.ApprovalsView(controller),
            "Settings": settings.SettingsView(controller),
        }
        for view in self._views.values():
            self._stack.addWidget(view)
        root.addWidget(self._stack)

        self._controller.tasks_changed.connect(self._views["Tasks"].refresh)
        self._controller.inbox_changed.connect(lambda: None)

    def tray_icon(self):
        return self._tray

    def _on_rail_changed(self, item: QListWidgetItem) -> None:
        if item is None:
            return
        label = item.data(Qt.UserRole)
        view = self._views.get(label)
        if view is not None:
            if label == "Settings":
                view.refresh_autostart()
            self._stack.setCurrentWidget(view)

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
