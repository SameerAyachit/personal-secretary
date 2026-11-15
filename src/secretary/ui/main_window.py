"""Main window: left-rail navigation + stacked content, hide-to-tray (plan §12.1, C-3)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from secretary.controller import Controller
from secretary.ui.theme import apply_theme, resolve_theme
from secretary.ui.tray import TrayIcon
from secretary.ui.views import (
    approvals,
    chat,
    events,
    inbox,
    mail,
    planner,
    research,
    settings,
    tasks,
    today,
)
from secretary.util.main_thread_watchdog import MainThreadWatchdog

_RAIL_TOOLTIPS = {
    "Inbox": "Notification log: reminders, research briefs and email results",
    "Mail": "Gmail messages the assistant has classified (read-only)",
    "Approvals": "Emails drafted by the assistant and actions waiting for your OK",
}


class MainWindow(QMainWindow):
    """Single Secretary window. Closing hides to tray; tray Quit is the only exit."""

    def __init__(
        self,
        controller: Controller,
        watchdog: MainThreadWatchdog | None = None,
    ) -> None:
        super().__init__()
        self._controller = controller

        # Heartbeat for the main-thread watchdog (plan C-27): beat every 50 ms
        # on the GUI thread so a stalled main thread is detected and traced.
        if watchdog is not None:
            self._heartbeat = QTimer(self)
            self._heartbeat.setInterval(50)
            self._heartbeat.timeout.connect(watchdog.beat)  # type: ignore[arg-type]
            self._heartbeat.start()

        self.setWindowTitle("Secretary")
        self.setMinimumSize(900, 600)

        stored = self._controller.get_config().get("theme", "light")
        apply_theme(QApplication.instance(), resolve_theme(stored))

        # Follow the Windows color scheme while the app runs ("system" theme).
        QGuiApplication.styleHints().colorSchemeChanged.connect(
            self._on_system_theme_changed
        )

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Left rail.
        self._rail = QListWidget()
        self._rail.setFixedWidth(200)
        self._rail.setFrameStyle(0)  # no frame
        for label in ("Today", "Chat", "Tasks", "Calendar", "Inbox", "Mail", "Approvals", "Planner", "Research", "Settings"):
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, label)
            if label in _RAIL_TOOLTIPS:
                item.setToolTip(_RAIL_TOOLTIPS[label])
            self._rail.addItem(item)
        self._rail.setCurrentRow(0)
        self._rail.currentItemChanged.connect(self._on_rail_changed)
        root.addWidget(self._rail)

        # Content area.
        self._stack = QStackedWidget()

        # Tray icon with Open/Quit menu and an inbox overflow hint (plan C-4).
        self._tray = TrayIcon(self, controller)
        self._tray.item_activated.connect(self.show_inbox)

        self._views = {
            "Today": today.TodayView(controller),
            "Chat": chat.ChatView(controller),
            "Tasks": tasks.TasksView(controller),
            "Calendar": events.EventsView(controller),
            "Inbox": inbox.InboxView(controller),
            "Mail": mail.MailView(controller),
            "Approvals": approvals.ApprovalsView(controller),
            "Planner": planner.PlannerView(controller),
            "Research": research.ResearchView(controller),
            "Settings": settings.SettingsView(controller),
        }
        for view in self._views.values():
            self._stack.addWidget(view)
        root.addWidget(self._stack)

        self._controller.tasks_changed.connect(self._views["Tasks"].refresh)
        self._controller.open_research_brief.connect(self._open_research_brief)
        self._controller.inbox_changed.connect(self.refresh_tray)

    def _on_system_theme_changed(self, scheme: Qt.ColorScheme) -> None:
        """Re-apply the theme when Windows changes its color scheme ("system")."""
        stored = self._controller.get_config().get("theme", "light")
        if stored == "system":
            apply_theme(QApplication.instance(), resolve_theme(stored))

    def tray_icon(self):
        return self._tray.tray_icon()

    def refresh_tray(self) -> None:
        """Refresh the tray menu/badge from the current inbox state."""
        self._tray.refresh()

    @Slot()
    def show_inbox(self) -> None:
        """Show the Inbox view (chosen from a tray menu item)."""
        for i in range(self._rail.count()):
            if self._rail.item(i).data(Qt.UserRole) == "Inbox":
                self._rail.setCurrentRow(i)
                break
        self._stack.setCurrentWidget(self._views["Inbox"])
        self.show_window()

    @Slot(int)
    def _open_research_brief(self, brief_id: int) -> None:
        """Switch to the Research tab and show one brief (from an Inbox item)."""
        for i in range(self._rail.count()):
            if self._rail.item(i).data(Qt.UserRole) == "Research":
                self._rail.setCurrentRow(i)
                break
        self._views["Research"].show_brief(brief_id)

    def _on_rail_changed(self, item: QListWidgetItem) -> None:
        if item is None:
            return
        label = item.data(Qt.UserRole)
        view = self._views.get(label)
        if view is not None:
            if label == "Settings":
                view.refresh_autostart()
            elif hasattr(view, "refresh"):
                view.refresh()  # never show a stale list when navigating
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
