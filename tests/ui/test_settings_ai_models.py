"""Settings > AI model dropdown: usable immediately, filled lazily, keeps the chosen model."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QTabWidget

from secretary.controller import Controller
from secretary.ui.views.settings import SettingsView

ULTRA = "nvidia/nemotron-3-ultra-550b-a55b"
LISTED = ["abacusai/dracarys", ULTRA, "nvidia/nemotron-3.5-super-vl-120b-a12b", "z-ai/other"]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _DummyConn:
    pass


def _view() -> SettingsView:
    return SettingsView(Controller(_DummyConn()))


def _items(view: SettingsView) -> list[str]:
    return [view._ai_model.itemText(i) for i in range(view._ai_model.count())]


def test_model_dropdown_is_usable_before_any_list_arrives(qapp):
    view = _view()
    assert view._ai_model.isEnabled()
    assert view._ai_model.currentText() == ULTRA  # the configured default


def test_models_list_keeps_the_configured_model_selected(qapp):
    view = _view()
    view._on_models_loaded("nvidia", LISTED)
    assert view._ai_model.isEnabled()
    assert view._ai_model.currentText() == ULTRA  # not the alphabetically first entry
    assert _items(view) == LISTED


def test_user_choice_survives_a_reload(qapp):
    view = _view()
    view._on_models_loaded("nvidia", LISTED)
    view._ai_model.setCurrentText("nvidia/nemotron-3.5-super-vl-120b-a12b")
    view._on_models_loaded("nvidia", LISTED)
    assert view._ai_model.currentText() == "nvidia/nemotron-3.5-super-vl-120b-a12b"


def test_failed_listing_keeps_a_working_dropdown(qapp):
    view = _view()
    view._on_models_loaded("nvidia", [])
    assert view._ai_model.isEnabled()
    assert view._ai_model.currentText() == ULTRA


def test_model_list_is_requested_when_the_ai_tab_opens_not_at_construction(qapp):
    controller = Controller(_DummyConn())
    with patch.object(controller, "get_available_models") as request:
        view = SettingsView(controller)
        request.assert_not_called()  # no network work while building the view
        tabs = view.findChild(QTabWidget)
        tabs.setCurrentIndex(1)  # AI
        request.assert_called_once_with("nvidia")
        tabs.setCurrentIndex(0)
        tabs.setCurrentIndex(1)
        request.assert_called_once()  # only on first open
