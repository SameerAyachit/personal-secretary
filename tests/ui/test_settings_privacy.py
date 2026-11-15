"""Settings > Privacy: says plainly what is sent where, including NVIDIA's trial terms (plan 12.2)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import tempfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QTabWidget

from secretary.config import load_config, save_config
from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.ui.views.settings import SettingsView


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "p.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


def _privacy_text(view: SettingsView) -> str:
    tabs = view.findChild(QTabWidget)
    index = next(i for i in range(tabs.count()) if tabs.tabText(i) == "Privacy")
    tabs.setCurrentIndex(0)  # leave and re-enter, as a user switching tabs does
    tabs.setCurrentIndex(index)
    return "\n".join(label.text() for label in tabs.widget(index).findChildren(QLabel))


def test_privacy_tab_exists_and_states_the_nvidia_trial_terms(qapp):
    conn = _conn()
    try:
        text = _privacy_text(SettingsView(Controller(conn)))
        assert "NVIDIA" in text and "trial" in text.lower()
        assert "record" in text.lower() and "improve" in text.lower()
        for topic in ("chat", "email", "task", "calendar"):
            assert topic in text.lower(), topic
    finally:
        conn.close()


def test_privacy_tab_lists_every_outbound_destination(qapp):
    conn = _conn()
    try:
        text = _privacy_text(SettingsView(Controller(conn)))
        assert "integrate.api.nvidia.com" in text  # the LLM host, taken from config
        assert "DuckDuckGo" in text
        assert "Google" in text
        assert "GitHub" in text
        assert "Credential Manager" in text and "redact" in text.lower()
        assert "no telemetry" in text.lower()
    finally:
        conn.close()


def test_a_non_nvidia_provider_does_not_get_the_nvidia_warning(qapp):
    conn = _conn()
    try:
        cfg = load_config()
        cfg.llm.active = "gemini"
        cfg.llm.providers["gemini"].base_url = "http://localhost:11434/v1"
        save_config(cfg)
        view = SettingsView(Controller(conn))
        text = _privacy_text(view)
        assert "localhost" in text
        assert "trial" not in text.lower()
    finally:
        conn.close()


def test_update_check_line_follows_the_switch(qapp):
    conn = _conn()
    try:
        controller = Controller(conn)
        view = SettingsView(controller)
        assert "once a day" in _privacy_text(view)
        controller.set_update_check(False)
        assert "turned off" in _privacy_text(view).lower()
    finally:
        conn.close()


def test_privacy_info_never_contains_secrets(qapp):
    conn = _conn()
    try:
        info = Controller(conn).get_privacy_info()
        assert set(info) == {"provider", "host", "nvidia_trial", "update_check"}
        assert info["nvidia_trial"] is True and info["host"] == "integrate.api.nvidia.com"
    finally:
        conn.close()
