"""Notification layers (plan §11).

Order: inbox row (written by the caller first, source of truth) -> Windows toast
via desktop-notifier (best-effort) -> popup card (frameless, always-on-top) for
priority reminders or whenever the toast layer fails -> tray badge/tooltip.

All notifier calls are wrapped in try/except and logged; a notifier failure
never prevents the inbox row from existing or the popup from showing.

``notify`` is safe to call from any thread: it emits a queued signal so the
toast/popup is shown on the GUI thread, never blocking or touching Qt from a
background thread.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal

from secretary.config import load_config
from secretary.notify.popup import PopupCard

logger = logging.getLogger("secretary")

try:  # desktop-notifier is optional
    from desktop_notifier import DesktopNotifierSync
except Exception as exc:  # not installed
    logger.warning("desktop-notifier import failed: %s", exc)
    DesktopNotifierSync = None


class Notifier(QObject):
    """Toast + popup-card notification layer with a tray badge."""

    # Emitted when a notification is shown (for the UI to reflect state).
    notified = Signal(str, str)  # title, body
    # Emitted when a notification should be shown; connected to
    # :meth:`_show_notification` with a queued connection so background threads
    # can request notifications without touching Qt directly.
    toast_failed = Signal(str, str)  # title, body; delivered queued to the GUI thread
    show_notification = Signal(str, str, bool, int)  # title, body, priority, inbox_id (0 = none)

    def __init__(self, tray_icon=None) -> None:
        super().__init__()
        self._tray = tray_icon
        self._desktop_sync = None
        if DesktopNotifierSync is not None:
            try:
                self._desktop_sync = DesktopNotifierSync()
            except Exception as exc:  # AUMID missing when run unpackaged, etc.
                logger.warning("desktop-notifier unavailable: %s", exc)
                self._desktop_sync = None
        # Queued connection: display happens on the GUI thread regardless of
        # which thread calls :meth:`notify`.
        self.show_notification.connect(self._show_notification, Qt.QueuedConnection)
        self.toast_failed.connect(self._tray_message, Qt.QueuedConnection)
        # Keep popup cards alive until they are closed so they are not
        # garbage-collected as soon as _show_popup returns (plan C-6).
        self._popups: set[PopupCard] = set()
        # Set by the composition root: handler("done"|"snooze", inbox_id).
        self.action_handler: Callable[[str, int], None] | None = None

    def notify(
        self, title: str, body: str, priority: bool = False, inbox_id: int | None = None
    ) -> bool:
        """Request a notification.

        Safe to call from any thread; the toast/popup is shown on the GUI
        thread via a queued signal. Returns True once the display is requested
        (not once the toast is shown).
        """
        self.show_notification.emit(title, body, priority, inbox_id or 0)
        return True

    def _show_notification(self, title: str, body: str, priority: bool, inbox_id: int = 0) -> None:
        """Show a notification on the GUI thread without blocking it.

        The popup is fast Qt work and stays on the GUI thread. The desktop
        toast send blocks (desktop-notifier's send() runs a WinRT call through
        run_until_complete on the calling thread) -- running it here froze the
        whole app for up to a minute when a reminder fired. It is therefore
        pumped onto a background thread; the inbox row remains the fallback.
        """
        settings = load_config().notifications
        if (priority or self._desktop_sync is None) and settings.popup_card:
            if inbox_id:
                self._show_popup(title, body, inbox_id)
            else:
                self._show_popup(title, body)
        if self._desktop_sync is not None:
            if settings.toast:
                self._send_toast(title, body)
        else:
            self._tray_message(title, body)
        self.notified.emit(title, body)

    def _send_toast(self, title: str, body: str) -> None:
        """Send the desktop toast on a background thread so the GUI never blocks."""

        def _run() -> None:
            try:
                self._desktop_sync.send(title=title, message=body)
            except Exception as exc:  # one failed toast must not kill the notifier
                logger.warning("toast failed: %s", exc)
                self.toast_failed.emit(title, body)  # fall back to a tray message
                self._desktop_sync = None

        threading.Thread(target=_run, daemon=True, name="secretary-toast").start()

    def _tray_message(self, title: str, body: str) -> None:
        """Fallback toast through the system tray when desktop-notifier is absent."""
        if self._tray is not None and self._tray.isVisible():
            self._tray.showMessage(title, body)

    def _show_popup(self, title: str, body: str, inbox_id: int = 0) -> None:
        popup = PopupCard(title, body)
        if inbox_id:
            popup.done.connect(lambda: self._act("done", inbox_id))
            popup.snooze.connect(lambda: self._act("snooze", inbox_id))
        popup.show_popup()
        # Keep a reference so the card is not GC'd when this method returns.
        self._popups.add(popup)
        popup.done.connect(lambda: self._popups.discard(popup))
        popup.destroyed.connect(lambda: self._popups.discard(popup))

    def _act(self, kind: str, inbox_id: int) -> None:
        if self.action_handler is not None:
            self.action_handler(kind, inbox_id)

    def set_tray(self, tray_icon) -> None:
        self._tray = tray_icon

    def set_tray_badge(self, count: int) -> None:
        """Update the tray tooltip with the unacknowledged count."""
        if self._tray is None:
            return
        try:
            self._tray.setToolTip(f"Secretary ({count} unread)" if count else "Secretary")
        except Exception as exc:
            logger.warning("tray badge failed: %s", exc)
