"""Pytest session fixtures.

PySide6 on Windows can abort with ``0xC0000409`` (stack buffer overrun) when a
QApplication is destroyed while the interpreter is tearing down. Tests share one
QApplication through ``QApplication.instance()``, so tear it down deterministically
after all tests while the interpreter is still intact: close any remaining
top-level widgets, quit the application, and collect Qt objects so they are not
torn down mid-interpreter-shutdown.

CRITICAL: tests must NEVER touch the real Windows Credential Manager or the real
project-root credentials.json, because test runs would overwrite/delete real
keys. This session installs an in-memory keyring backend and points the data
root / credentials.json at temp paths for EVERY test before any test code runs.
"""

from __future__ import annotations

import gc
import os
import tempfile
from collections.abc import MutableMapping
from pathlib import Path

import keyring
import keyring.backend
import keyring.errors
import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _InMemoryKeyring(keyring.backend.KeyringBackend):
    """In-memory keyring backend: never touches Windows Credential Manager."""

    priority = 1.0

    def __init__(self) -> None:
        self._store: MutableMapping[tuple[str, str], str] = {}
        super().__init__()

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self._store.pop((service, username), None)


_original_backend = keyring.get_keyring()
_data_root = Path(tempfile.mkdtemp(prefix="secretary-test-"))
_credentials_path = _data_root / "credentials.json"
_original_env = {
    "SECRETARY_DATA_ROOT": os.environ.get("SECRETARY_DATA_ROOT"),
    "SECRETARY_CREDENTIALS": os.environ.get("SECRETARY_CREDENTIALS"),
}


@pytest.fixture(scope="session", autouse=True)
def _guard_keyring_and_paths():
    """Route keyring to an in-memory backend and data/credentials to temp paths.

    Active for every test, session-wide, so no test can write to real Windows
    Credential Manager or the real project-root credentials.json.
    """
    keyring.set_keyring(_InMemoryKeyring())
    os.environ["SECRETARY_DATA_ROOT"] = str(_data_root)
    os.environ["SECRETARY_CREDENTIALS"] = str(_credentials_path)
    yield
    keyring.set_keyring(_original_backend)
    for name, value in _original_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


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
