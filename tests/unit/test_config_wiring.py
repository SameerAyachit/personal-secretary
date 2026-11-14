"""Config keys that used to be ignored now change behaviour."""

from __future__ import annotations

import copy
import sqlite3
import tempfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

import secretary.notify.notifier as notifier_module
from secretary.config import _DEFAULTS, Config
from secretary.integrations.search.provider import SearchCache, SearchResult
from secretary.notify.notifier import Notifier
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.tools.research import ResearchBrief


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "w.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


def test_search_cache_ttl_comes_from_config_value():
    conn = _conn()
    results = [SearchResult("t", "https://example.com", "s")]
    fresh = SearchCache(conn, ttl_hours=24)
    fresh.set("aqi satellite", results)
    assert [r.url for r in fresh.get("AQI satellite ")] == ["https://example.com"]  # key is normalised
    assert SearchCache(conn, ttl_hours=0).get("aqi satellite") is None  # already expired


class _Provider:
    def search(self, query: str, n: int = 5):
        return [SearchResult(f"t{i}", f"https://e.com/{query}/{i}", "s") for i in range(n)]


def test_research_source_limit_is_configurable():
    brief = ResearchBrief(llm=None, search_provider=_Provider(), max_sources=2)
    assert len(brief._search(["a", "b", "c"])) == 2


def test_notification_toggles_are_honoured(monkeypatch, qapp):
    cfg = Config.model_validate(copy.deepcopy(_DEFAULTS))
    cfg.notifications.popup_card = False
    cfg.notifications.toast = False
    monkeypatch.setattr(notifier_module, "load_config", lambda path=None: cfg)

    sent: list[str] = []

    class _Desktop:
        def send(self, title, message):
            sent.append(title)

    notifier = Notifier()
    notifier._desktop_sync = _Desktop()
    shown: list = []
    notifier._show_popup = lambda *a, **k: shown.append(a)  # type: ignore[method-assign]
    notifier._show_notification("t", "b", True)
    assert shown == [] and sent == []
