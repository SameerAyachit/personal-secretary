"""Settings view (offscreen, plan §12 / secretary-ui-design skill)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from secretary.controller import Controller
from secretary.ui.views.settings import SettingsView


class _DummyConn:
    """Controller only stores the connection; autostart never touches it."""


def test_autostart_checkbox_reflects_controller_state():
    controller = Controller(_DummyConn())
    with patch.object(controller, "get_autostart", return_value=True):
        view = SettingsView(controller)
    assert view._autostart.isChecked()
    assert view._autostart.accessibleName() == "Start at login"


def test_autostart_checkbox_unchecked_when_disabled():
    controller = Controller(_DummyConn())
    with patch.object(controller, "get_autostart", return_value=False):
        view = SettingsView(controller)
    assert not view._autostart.isChecked()


def test_toggle_calls_controller_set_autostart():
    controller = Controller(_DummyConn())
    view = SettingsView(controller)
    with patch.object(controller, "set_autostart") as mock:
        view._autostart.click()
        mock.assert_called_once_with(True)


def test_toggle_reverts_when_run_key_cannot_be_written():
    controller = Controller(_DummyConn())
    view = SettingsView(controller)
    with patch.object(
        controller, "set_autostart", side_effect=OSError("access denied")
    ):
        view._autostart.click()
    assert not view._autostart.isChecked()


def test_refresh_autostart_reads_true_state():
    controller = Controller(_DummyConn())
    view = SettingsView(controller)
    view._autostart.setChecked(True)
    with patch.object(controller, "get_autostart", return_value=False):
        view.refresh_autostart()
    assert not view._autostart.isChecked()
