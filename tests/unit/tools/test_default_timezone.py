"""The user's configured timezone is the default everywhere; the model can't override it."""

from __future__ import annotations

import asyncio
import copy
import sqlite3
import tempfile
from pathlib import Path

import secretary.config as config_module
from secretary.agent.loop import _execute_call, _hide_tz
from secretary.config import _DEFAULTS, Config, default_timezone
from secretary.llm.base import ToolCall
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.tools import reminders as reminders_tools
from secretary.tools.registry import Registry


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "tz.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


def _use_timezone(monkeypatch, tz: str) -> None:
    cfg = Config.model_validate(copy.deepcopy(_DEFAULTS))
    cfg.app.timezone = tz
    monkeypatch.setattr(config_module, "load_config", lambda path=None: cfg)


def test_default_timezone_reads_config(monkeypatch):
    _use_timezone(monkeypatch, "America/New_York")
    assert default_timezone() == "America/New_York"


def test_reminder_uses_configured_timezone_by_default(monkeypatch):
    _use_timezone(monkeypatch, "America/New_York")
    out = reminders_tools.reminder_create(
        _conn(), "t-tz", {"title": "stretch", "when_text": "in 10 minutes"}
    )
    assert "EST" in out["fire_at_local"] or "EDT" in out["fire_at_local"]


def test_turn_timezone_overrides_model_and_is_hidden_from_schema(monkeypatch):
    _use_timezone(monkeypatch, "Asia/Kolkata")
    registry = Registry()
    reminders_tools.register(registry)
    schema = next(s for s in registry.schemas() if s["name"] == "reminder_create")
    assert "tz" in schema["parameters"]["properties"]
    hidden = _hide_tz(schema)
    assert "tz" not in hidden["parameters"]["properties"]
    assert "tz" in schema["parameters"]["properties"]  # original untouched

    call = ToolCall(
        call_id="1",
        name="reminder_create",
        args={"title": "stretch", "when_text": "in 10 minutes", "tz": "Pacific/Auckland"},
    )
    out = asyncio.run(_execute_call(call, registry, _conn(), "t-1", tz="America/New_York"))
    assert "EST" in out["fire_at_local"] or "EDT" in out["fire_at_local"]
