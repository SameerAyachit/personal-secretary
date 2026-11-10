"""Pytest session fixtures.

PySide6 on Windows can abort with ``0xC0000409`` / an access violation when a
QApplication is destroyed while the interpreter is tearing down. Tests share one
QApplication through ``QApplication.instance()``, so quit it cleanly at the end
of the session instead of leaving it to be torn down mid-interpreter-shutdown.
"""

from __future__ import annotations

import os

import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def _quit_qt_application():
    """Quit the shared QApplication after all tests are done."""
    yield

    app = QApplication.instance()
    if app is not None:
        app.quit()
