"""Tests for notify/notifier.py: toast, popup fallback, failure resilience (plan §11).

``notify()`` is safe to call from any thread: it emits a queued signal so the
toast/popup is shown on the GUI thread and never blocks the caller. The desktop
toast send itself is pumped onto a background thread because
``desktop-notifier``'s ``send()`` blocks the calling thread (WinRT
``run_until_complete``) -- running it on the GUI thread froze the app for up to
a minute when a reminder fired.
"""

import gc
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from secretary.notify.notifier import Notifier
from secretary.notify.popup import PopupCard


class _RecordingDesktop:
    """Desktop-notifier fake that records send() calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def send(self, title: str, message: str) -> None:
        self.calls.append((title, message))


class _FailingDesktop:
    """Desktop-notifier fake whose send() always raises."""

    def send(self, title: str, message: str) -> None:
        raise RuntimeError("toast is broken")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _wait_for(toast, timeout: float = 2.0) -> bool:
    """Poll until the background toast thread has called send()."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if toast.calls:
            return True
        time.sleep(0.01)
    return False


def test_notify_returns_true_and_sends_desktop_toast(qapp):
    notifier = Notifier()
    desktop = _RecordingDesktop()
    notifier._desktop_sync = desktop
    shown = []

    def fake_show_popup(self, title, body):
        shown.append((title, body))

    notifier._show_popup = fake_show_popup.__get__(notifier, Notifier)

    assert notifier.notify("title", "body") is True
    app = QApplication.instance()
    app.processEvents()  # deliver the queued _show_notification on the GUI thread
    # Non-priority with a desktop backend: toast only, no popup.
    assert _wait_for(desktop)
    assert desktop.calls == [("title", "body")]
    assert shown == []


def test_notify_priority_shows_popup(qapp):
    notifier = Notifier()
    desktop = _RecordingDesktop()
    notifier._desktop_sync = desktop
    shown = []

    def fake_show_popup(self, title, body):
        shown.append((title, body))

    notifier._show_popup = fake_show_popup.__get__(notifier, Notifier)

    assert notifier.notify("title", "body", priority=True) is True
    app = QApplication.instance()
    app.processEvents()  # deliver the queued _show_notification on the GUI thread
    assert shown == [("title", "body")]
    assert _wait_for(desktop)
    assert desktop.calls == [("title", "body")]


def test_notify_no_desktop_shows_popup(qapp):
    notifier = Notifier()
    notifier._desktop_sync = None
    shown = []

    def fake_show_popup(self, title, body):
        shown.append((title, body))

    notifier._show_popup = fake_show_popup.__get__(notifier, Notifier)

    assert notifier.notify("title", "body", priority=True) is True
    app = QApplication.instance()
    app.processEvents()
    assert shown == [("title", "body")]


def test_notify_desktop_failure_still_returns_true(qapp):
    """A failing toast layer must not crash or block the caller; it is disabled."""
    notifier = Notifier()
    notifier._desktop_sync = _FailingDesktop()
    shown = []

    def fake_show_popup(self, title, body):
        shown.append((title, body))

    notifier._show_popup = fake_show_popup.__get__(notifier, Notifier)

    assert notifier.notify("title", "body") is True
    # Non-priority: no popup even though the toast failed (inbox row is the
    # source of truth); a second notify must not attempt the toast again.
    app = QApplication.instance()
    app.processEvents()
    assert shown == []
    assert notifier._desktop_sync is None
    # No desktop backend: the popup is the fallback, shown for every notify.
    notifier.notify("again", "body")
    app.processEvents()
    assert shown == [("again", "body")]


def test_set_tray_badge(qapp):
    notifier = Notifier()
    tray = MagicMock()
    notifier.set_tray(tray)
    notifier.set_tray_badge(3)
    tray.setToolTip.assert_called_once_with("Secretary (3 unread)")
    notifier.set_tray_badge(0)
    tray.setToolTip.assert_called_with("Secretary")


def test_popup_buttons_reach_action_handler_and_card_survives_gc(qapp):
    notifier = Notifier()
    notifier._desktop_sync = None  # popup path only
    seen: list[tuple[str, int]] = []
    notifier.action_handler = lambda kind, inbox_id: seen.append((kind, inbox_id))
    base = PopupCard._stack_offset
    notifier.notify("Reminder", "drink water", priority=True, inbox_id=7)
    qapp.processEvents()
    gc.collect()
    popups = list(notifier._popups)
    assert len(popups) == 1 and popups[0].isVisible()
    assert PopupCard._stack_offset == base + 1
    popups[0]._done_btn.click()
    assert seen == [("done", 7)]
    assert PopupCard._stack_offset == base  # slot released exactly once
