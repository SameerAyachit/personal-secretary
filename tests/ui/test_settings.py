"""Settings view (offscreen, plan §12 / secretary-ui-design skill)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

from secretary.config import load_config
from secretary.controller import Controller
from secretary.ui.views.settings import SettingsView


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _DummyConn:
    """Controller only stores the connection; autostart never touches it."""


def test_autostart_checkbox_reflects_controller_state(qapp):
    controller = Controller(_DummyConn())
    with patch.object(controller, "get_autostart", return_value=True):
        view = SettingsView(controller)
    assert view._autostart.isChecked()
    assert view._autostart.accessibleName() == "Start at login"


def test_autostart_checkbox_unchecked_when_disabled(qapp):
    controller = Controller(_DummyConn())
    with patch.object(controller, "get_autostart", return_value=False):
        view = SettingsView(controller)
    assert not view._autostart.isChecked()


def test_toggle_calls_controller_set_autostart(qapp):
    controller = Controller(_DummyConn())
    view = SettingsView(controller)
    with patch.object(controller, "set_autostart") as mock:
        view._autostart.click()
        mock.assert_called_once_with(True)


def test_toggle_reverts_when_run_key_cannot_be_written(qapp):
    controller = Controller(_DummyConn())
    view = SettingsView(controller)
    with patch.object(
        controller, "set_autostart", side_effect=OSError("access denied")
    ):
        view._autostart.click()
    assert not view._autostart.isChecked()


def test_refresh_autostart_reads_true_state(qapp):
    controller = Controller(_DummyConn())
    view = SettingsView(controller)
    view._autostart.setChecked(True)
    with patch.object(controller, "get_autostart", return_value=False):
        view.refresh_autostart()
    assert not view._autostart.isChecked()


def test_theme_round_trip(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))
    controller = Controller(_DummyConn())
    view = SettingsView(controller)
    assert view._theme.currentText() == "System"
    view._theme.setCurrentText("Dark")

    assert load_config().app.theme == "dark"
    view._theme.setCurrentText("System")
    assert load_config().app.theme == "system"
