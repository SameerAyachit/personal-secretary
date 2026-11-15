"""A reply must not describe the user's tasks/events/reminders unless a list tool ran."""

from __future__ import annotations

import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from secretary.agent.loop import _claims_listing, run_turn
from secretary.agent.router import Router
from secretary.llm.base import LLMResponse, ToolCall
from secretary.llm.fake import FakeLLM
from secretary.llm.limiter import Limiter
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import tasks as tasks_repo
from secretary.tools.registry import Registry
from secretary.tools.tasks import register as register_tasks


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "r.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


def _say(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=[], usage={}, headers={}, model="fake")


def _call(name: str, args: dict) -> LLMResponse:
    return LLMResponse(text="", tool_calls=[ToolCall(call_id="c1", name=name, args=args)],
                       usage={}, headers={}, model="fake")


async def _run(conn, llm, text="what are my tasks", history=None) -> str:
    registry = Registry()
    register_tasks(registry)
    ctx = {"turn_id": "t1", "now": "2026-11-15T09:00:00+05:30", "tz": "Asia/Kolkata",
           "today_iso": "2026-11-15", "history": history or []}
    limiter = Limiter(rpm=10000, tpm=100000, safety=1.0, clock=time.monotonic)
    return await run_turn(text, ctx, llm, limiter, Router(registry), registry, conn)


@pytest.mark.parametrize("text", [
    "You have 3 open tasks: 1. Buy milk 2. Call mom 3. Pay rent",
    "Here are your events for today:\n- Dentist 3pm\n- Standup 10am",
    "Your reminders: drink water at 5pm, stand up at 6pm.",
    "You have a meeting at 3pm and two tasks due today.",
    "Your tasks for today:\n1. Buy milk\n2. Call mom",
])
def test_invented_listings_are_detected(text):
    assert _claims_listing(text, "")


@pytest.mark.parametrize("text", [
    "",
    "Hello! How can I help?",
    "You have no open tasks.",
    "Which task do you mean?",
    "I can list your tasks if you like.",
    "Done, I added it.",
])
def test_ordinary_replies_are_not_listings(text):
    assert not _claims_listing(text, "")


def test_a_list_already_in_the_conversation_is_not_flagged():
    history = "assistant: Your tasks for today:\n1. Buy milk\n2. Call mom"
    assert not _claims_listing("Your tasks for today:\n1. Buy milk\n2. Call mom", history.lower())


@pytest.mark.asyncio
async def test_invented_list_is_retried_and_the_real_tool_is_used():
    conn = _conn()
    try:
        tasks_repo.create(conn, title="Real task", source="user")
        llm = FakeLLM()
        llm.add(_say("You have 2 open tasks: 1. Imaginary one 2. Another fake"))
        llm.add(_call("task_list", {"filter": "open"}))
        llm.add(_say("You have one open task: Real task."))
        reply = await _run(conn, llm)
        assert "Real task" in reply and "Imaginary" not in reply
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_persistent_invented_list_gets_an_honest_fallback():
    conn = _conn()
    try:
        llm = FakeLLM()
        llm.add(_say("You have 2 open tasks: 1. Imaginary one 2. Another fake"))
        llm.add(_say("You have 2 open tasks: 1. Imaginary one 2. Another fake"))
        reply = await _run(conn, llm)
        assert "Imaginary" not in reply
        assert "check" in reply.lower()
    finally:
        conn.close()
