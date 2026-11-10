"""E2E: chat send path through the real composition root (``python -m secretary``).

Bug: ``Controller.send_message`` accessed ``self.llm.active`` but
``OpenAICompatClient`` has no ``active`` attribute, so every chat turn raised
``AttributeError`` and no error bubble was shown. The active provider/model and
key must come from config via one helper (``get_active_llm_key``) that reads
the keyring service/name ``diagnose`` checks.

Covers:
  * no LLM key configured -> clear error bubble (turn_status / turn_finished)
  * FakeLLM configured -> "hey" gets a reply
"""
from __future__ import annotations

from pathlib import Path

import secretary.controller as cm
from secretary.agent.router import Router
from secretary.config import load_config, save_config
from secretary.controller import Controller, get_active_llm_key
from secretary.llm.base import LLMResponse
from secretary.llm.fake import FakeLLM
from secretary.llm.limiter import Limiter
from secretary.secrets import set_secret
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.tools import email as email_tools
from secretary.tools import events as events_tools
from secretary.tools import planning as planning_tools
from secretary.tools import registry as tools_registry
from secretary.tools import research as research_tools
from secretary.tools import tasks as tasks_tools


def _conn(tmp_path: Path) -> Connection:
    db = tmp_path / "chat.db"
    conn = Connection(db)
    migrate(conn._con, migrations_folder(), lambda: None)
    return conn


def _build_controller(conn, llm=None):
    registry = tools_registry.Registry()
    tasks_tools.register(registry)
    email_tools.register(registry)
    events_tools.register(registry)
    planning_tools.register(registry)
    research_tools.register(registry)
    router = Router(registry)
    router.route("tasks_add", ["task", "create", "add", "remind"])
    router.route("tasks_list", ["task", "list", "show", "remind"])
    router.route("reminders_add", ["remind", "reminder"])
    router.route("email_send", ["send", "email"])
    router.route("web_search", ["search", "web"])
    router.route("event_create", ["event", "calendar", "meeting", "appointment"])
    router.route("event_list", ["events", "calendar", "schedule", "agenda"])
    router.route("plan_day", ["plan", "planning", "schedule", "free", "slot"])
    router.route("research_brief", ["research", "brief", "summarize"])
    return Controller(
        conn,
        registry=registry,
        router=router,
        llm=llm,
        limiter=Limiter(rpm=60, tpm=6000, safety=0.7),
    )


def test_get_active_llm_key_reads_config_and_keyring(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))
    cfg = load_config()
    cfg.llm.active = "gemini"
    save_config(cfg)
    set_secret("llm_api_key:gemini", "gemini-key-123")

    assert get_active_llm_key() == "gemini-key-123"


def test_chat_no_llm_key_shows_error_bubble(monkeypatch, tmp_path):
    conn = _conn(tmp_path)
    controller = _build_controller(conn, llm=None)

    # No key configured -> error bubble, never reaches run_turn.
    monkeypatch.setattr(cm, "get_active_llm_key", lambda: None)

    statuses = []
    finished = []
    controller.turn_status.connect(statuses.append)
    controller.turn_finished.connect(finished.append)

    controller.send_message("hey")

    assert any("No LLM key configured" in s for s in statuses), statuses
    assert any("I don't have an LLM key configured" in f for f in finished), finished


def test_chat_hey_gets_reply(tmp_path):
    conn = _conn(tmp_path)
    # Configure a groq key so send_message reaches the agent loop with the FakeLLM.
    set_secret("llm_api_key:groq", "fake-key")
    llm = FakeLLM([
        LLMResponse(text="Hello there!", tool_calls=[], usage={}, headers={}, model="fake"),
    ])
    controller = _build_controller(conn, llm=llm)

    finished = []
    controller.turn_finished.connect(finished.append)

    controller.send_message("hey")

    assert any("Hello there!" in f for f in finished), finished
