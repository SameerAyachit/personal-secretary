"""Pytest session fixtures.

PySide6 on Windows can abort with ``0xC0000409`` (stack buffer overrun) when a
QApplication is destroyed while the interpreter is tearing down. Tests share one
QApplication through ``QApplication.instance()``, so tear it down deterministically
after all tests while the interpreter is still intact: close any remaining
top-level widgets, quit the application, and collect Qt objects so they are not
torn down mid-interpreter-shutdown.
"""

from __future__ import annotations

import gc
import os

import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def _quit_qt_application():
    """Tear down the shared QApplication and its widgets after all tests."""
    yield
    app = QApplication.instance()
    if app is None:
        return
    # Close (and drop references to) top-level widgets so they are not destroyed
    # by the interpreter while Qt is shutting down.
    for widget in list(app.topLevelWidgets()):
        widget.close()
        widget.deleteLater()
    app.quit()
    gc.collect()
