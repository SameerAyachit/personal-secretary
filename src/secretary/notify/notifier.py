"""Notification layers (plan §11).

Order: inbox row (written by the caller first, source of truth) -> Windows toast
via desktop-notifier (best-effort) -> popup card (frameless, always-on-top) for
priority reminders or whenever the toast layer fails -> tray badge/tooltip.

All notifier calls are wrapped in try/except and logged; a notifier failure
never prevents the inbox row from existing or the popup from showing.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QSystemTrayIcon

from secretary.notify.popup import PopupCard

logger = logging.getLogger("secretary")

try:  # desktop-notifier is optional
    from desktop_notifier import Notifier as DesktopNotifier
except Exception:
    DesktopNotifier = None


class Notifier(QObject):
    """Toast + popup-card notification layer with a tray badge."""

    # Emitted when a notification is shown (for the UI to reflect state).
    notified = Signal(str, str)  # title, body

    def __init__(self, tray_icon=None) -> None:
        super().__init__()
        self._tray = tray_icon
        self._desktop = None
        try:
            self._desktop = DesktopNotifier()
        except Exception:  # desktop-notifier may be unavailable at runtime
            logger.warning("desktop-notifier unavailable")

    def set_tray(self, tray_icon) -> None:
        self._tray = tray_icon

    def notify(self, title: str, body: str, priority: bool = False) -> bool:
        """Show a notification. Returns True if a toast was sent."""
        sent = False
        # 2. Windows toast (best-effort).
        if self._desktop is not None:
            try:
                self._desktop.send(title=title, message=body)
                sent = True
            except Exception as exc:
                logger.warning("toast failed: %s", exc)
        # 2b. Tray showMessage fallback.
        if not sent and self._tray is not None:
            try:
                self._tray.showMessage(title, body, QSystemTrayIcon.Information, 5000)
                sent = True
            except Exception as exc:
                logger.warning("tray showMessage failed: %s", exc)
        # 3. Popup card for priority reminders or whenever the toast layer fails.
        if priority or not sent:
            self._show_popup(title, body)
        self.notified.emit(title, body)
        return sent

    def _show_popup(self, title: str, body: str) -> None:
        popup = PopupCard(title, body)
        popup.show_popup()

    def set_tray_badge(self, count: int) -> None:
        """Update the tray tooltip with the unacknowledged count."""
        if self._tray is None:
            return
        try:
            self._tray.setToolTip(f"Secretary ({count} unread)" if count else "Secretary")
        except Exception as exc:
            logger.warning("tray badge failed: %s", exc)
