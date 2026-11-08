"""Tests for notify/notifier.py: toast, popup fallback, failure resilience (plan §11)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from secretary.notify.notifier import Notifier


class _FailingDesktop:
    """Desktop-notifier fake whose send() always raises."""

    def send(self, title, message):
        raise RuntimeError("toast is broken")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_notify_desktop_toast_sent(qapp):
    notifier = Notifier()
    notifier._desktop = MagicMock()
    assert notifier.notify("title", "body") is True
    notifier._desktop.send.assert_called_once_with(title="title", message="body")


def test_notify_desktop_failure_still_shows_popup(qapp):
    notifier = Notifier()
    notifier._desktop = _FailingDesktop()
    shown = []

    def fake_show_popup(self, title, body):
        shown.append((title, body))

    notifier._show_popup = fake_show_popup.__get__(notifier, Notifier)
    # Should not raise even though the toast layer fails.
    assert notifier.notify("title", "body") is False
    assert shown == [("title", "body")]


def test_notify_no_desktop_shows_popup(qapp):
    notifier = Notifier()
    notifier._desktop = None
    shown = []

    def fake_show_popup(self, title, body):
        shown.append((title, body))

    notifier._show_popup = fake_show_popup.__get__(notifier, Notifier)
    assert notifier.notify("title", "body", priority=True) is False
    assert shown == [("title", "body")]


def test_set_tray_badge(qapp):
    notifier = Notifier()
    tray = MagicMock()
    notifier.set_tray(tray)
    notifier.set_tray_badge(3)
    tray.setToolTip.assert_called_once_with("Secretary (3 unread)")
    notifier.set_tray_badge(0)
    tray.setToolTip.assert_called_with("Secretary")
