"""Empty state widget tests (offscreen)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from secretary.ui.widgets.empty_state import EmptyState


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_empty_state_shows_title(qapp):
    view = EmptyState("Nothing here yet.")
    assert view._title.text() == "Nothing here yet."
    assert view.findChild(QPushButton) is None


def test_empty_state_action(qapp):
    clicked = []

    def action() -> None:
        clicked.append(True)

    view = EmptyState("Nothing here yet.", "Add something", action)
    btn = view.findChild(QPushButton)
    assert btn is not None
    assert btn.text() == "Add something"
    btn.click()
    assert clicked == [True]


def test_empty_state_without_action(qapp):
    view = EmptyState("Nothing here yet.")
    assert view.findChild(QPushButton) is None
    labels = [lbl.text() for lbl in view.findChildren(QLabel)]
    assert labels == ["Nothing here yet."]
