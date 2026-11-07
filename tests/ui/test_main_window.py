"""Tests for the main window and popup card (offscreen, plan §12 / P0-04 spike)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from secretary.notify.popup import PopupCard
from secretary.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_main_window_hides_instead_of_quitting(qapp):
    # No QApplication should be owned by the test; closing must not quit.
    app = QApplication.instance()
    assert app is not None
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow(app)
    window.show()
    assert window.isVisible()
    # Simulate a close: closeEvent should ignore and hide.
    event = QCloseEvent()
    window.closeEvent(event)
    assert not window.isVisible()
    # The application must still be running (not quit).
    assert QApplication.instance() is not None


def test_popup_card_creation_and_position(qapp):
    popup = PopupCard(title="Reminder", body="drink water")
    assert popup.windowFlags() & Qt.FramelessWindowHint
    assert popup.windowFlags() & Qt.WindowStaysOnTopHint
    popup.show_popup()
    assert popup.isVisible()
    screen = QApplication.primaryScreen()
    geo = screen.availableGeometry()
    # Bottom-right: within screen bounds.
    assert popup.x() + popup.width() <= geo.right()
    assert popup.y() + popup.height() <= geo.bottom()
    popup.close_popup()
    assert not popup.isVisible()
