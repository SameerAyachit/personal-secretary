"""Main window: left-rail navigation + stacked content, hide-to-tray (plan §12.1, C-3)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
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

        # Content area: an "Update available" banner (plan 18.3) above the stacked views.
        self._stack = QStackedWidget()
        self._update_tag = ""
        self._update_url = ""
        self._update_banner = QFrame()
        self._update_banner.setObjectName("Card")
        banner_row = QHBoxLayout(self._update_banner)
        banner_row.setContentsMargins(12, 8, 12, 8)
        self._update_text = QLabel("")
        self._update_text.setWordWrap(True)
        self._open_update = QPushButton("Open release page")
        self._open_update.setObjectName("Accent")
        self._open_update.setAccessibleName("Open the release page")
        self._open_update.clicked.connect(self._open_update_page)
        self._dismiss_update = QPushButton("Dismiss")
        self._dismiss_update.setAccessibleName("Dismiss the update notice")
        self._dismiss_update.clicked.connect(self._on_dismiss_update)
        banner_row.addWidget(self._update_text, 1)
        banner_row.addWidget(self._open_update)
        banner_row.addWidget(self._dismiss_update)
        self._update_banner.hide()

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
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._update_banner)
        content_layout.addWidget(self._stack, 1)
        root.addWidget(content, 1)

        self._controller.update_found.connect(self._show_update)
        self._show_update(self._controller.update_info())

        self._controller.tasks_changed.connect(self._views["Tasks"].refresh)
        self._controller.open_research_brief.connect(self._open_research_brief)
        self._controller.draft_reply_requested.connect(self._prefill_chat)
        self._controller.inbox_changed.connect(self.refresh_tray)

    @Slot(dict)
    def _show_update(self, info: dict | None) -> None:
        """Show the banner for a newer release, or hide it (also when the switch is off)."""
        info = self._controller.update_info() if info else None
        if not info:
            self._update_banner.hide()
            return
        self._update_tag, self._update_url = info["tag"], info["url"]
        self._update_text.setText(f"Update available: Secretary {info['tag']} is out.")
        self._update_banner.show()

    def _open_update_page(self) -> None:
        if self._update_url.startswith("https://github.com/"):
            QDesktopServices.openUrl(QUrl(self._update_url))

    def _on_dismiss_update(self) -> None:
        self._controller.dismiss_update(self._update_tag)
        self._update_banner.hide()

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

    @Slot(str)
    def _prefill_chat(self, text: str) -> None:
        """Open Chat with ``text`` ready in the input (from the Mail view)."""
        for i in range(self._rail.count()):
            if self._rail.item(i).data(Qt.UserRole) == "Chat":
                self._rail.setCurrentRow(i)
                break
        self._stack.setCurrentWidget(self._views["Chat"])
        self._views["Chat"].prefill(text)

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
