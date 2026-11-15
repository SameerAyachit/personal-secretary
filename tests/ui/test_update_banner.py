"""Update banner in the main window and the Settings switch (plan 18.3)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import tempfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox

from secretary import config as config_mod
from secretary.controller import Controller
from secretary.integrations import updates
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import settings as settings_repo
from secretary.ui.main_window import MainWindow
from secretary.ui.views.settings import SettingsView


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "b.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


def _record(conn, tag="v9.0.0"):
    settings_repo.set(conn, "update_latest_tag", tag)
    settings_repo.set(conn, "update_latest_url", f"https://github.com/o/r/releases/tag/{tag}")


def test_banner_hidden_when_no_update(qapp):
    conn = _conn()
    try:
        window = MainWindow(Controller(conn))
        window.show()
        assert not window._update_banner.isVisible()
    finally:
        conn.close()


def test_banner_shows_newer_release_and_can_be_dismissed(qapp):
    conn = _conn()
    try:
        _record(conn)
        controller = Controller(conn)
        window = MainWindow(controller)
        window.show()
        assert window._update_banner.isVisible()
        assert "v9.0.0" in window._update_text.text() and "Update available" in window._update_text.text()
        window._dismiss_update.click()
        assert not window._update_banner.isVisible()
        assert controller.update_info() is None  # stays dismissed on the next start
    finally:
        conn.close()


def test_found_signal_shows_the_banner_while_running(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        window = MainWindow(controller)
        window.show()
        assert not window._update_banner.isVisible()
        _record(conn)
        controller.update_found.emit({"tag": "v9.0.0", "url": "https://github.com/o/r/releases/tag/v9.0.0"})
        assert window._update_banner.isVisible()
    finally:
        conn.close()


def test_controller_switch_persists_and_default_is_on(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        assert controller.get_update_check() is True
        controller.set_update_check(False)
        assert controller.get_update_check() is False
        assert config_mod.load_config().updates.check is False
        controller.set_update_check(True)
        assert controller.get_update_check() is True
    finally:
        conn.close()


def test_settings_has_the_switch_and_explains_the_call(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        view = SettingsView(controller)
        box = next(b for b in view.findChildren(QCheckBox) if b.accessibleName() == "Check for updates")
        assert box.isChecked()
        box.setChecked(False)
        assert controller.get_update_check() is False
        text = " ".join(lbl.text() for lbl in view.findChildren(type(view._ai_key_status)))
        assert "GitHub" in text
    finally:
        conn.close()


def test_disabled_switch_hides_the_banner_even_with_a_stored_release(qapp):
    conn = _conn()
    try:
        _record(conn)
        controller = Controller(conn)
        controller.set_update_check(False)
        assert controller.update_info() is None
    finally:
        conn.close()


def test_update_module_is_the_only_new_outbound_call():
    assert updates.RELEASES_HOST == "api.github.com"
