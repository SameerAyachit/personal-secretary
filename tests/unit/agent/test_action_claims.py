"""A reply must not claim a task/reminder/event/note was created or changed unless a tool ran."""

from __future__ import annotations

import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from secretary.agent.loop import _claims_action, run_turn
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
    tmp = Path(tempfile.mkdtemp()) / "a.db"
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


def _llm(*responses: LLMResponse) -> FakeLLM:
    fake = FakeLLM()
    for response in responses:
        fake.add(response)
    return fake


async def _run(conn, llm, text="add a task to buy milk") -> str:
    registry = Registry()
    register_tasks(registry)
    router = Router(registry)
    ctx = {"turn_id": "t1", "now": "2026-11-15T09:00:00+05:30", "tz": "Asia/Kolkata",
           "today_iso": "2026-11-15"}
    limiter = Limiter(rpm=10000, tpm=100000, safety=1.0, clock=time.monotonic)
    return await run_turn(text, ctx, llm, limiter, router, registry, conn)


@pytest.mark.parametrize("text", [
    "I've added the task to buy milk.",
    "Done! Your reminder is set for 5pm.",
    "I rescheduled the meeting to 3pm.",
    "Task created: buy milk",
    "Note saved.",
    "I marked it as completed.",
    "Draft saved (ID 29).",
])
def test_claims_are_detected(text):
    assert _claims_action(text)


@pytest.mark.parametrize("text", [
    "",
    "Hello! How can I help?",
    "What time should I set the reminder for?",
    "Which task do you mean?",
    "I can add a task if you tell me the title.",
    "You have no open tasks.",
])
def test_ordinary_replies_are_not_claims(text):
    assert not _claims_action(text)


@pytest.mark.asyncio
async def test_invented_task_claim_is_retried_and_really_created():
    conn = _conn()
    try:
        llm = _llm(
            _say("I've added the task to buy milk."),
            _call("task_create", {"title": "buy milk"}),
            _say("Added: buy milk."),
        )
        reply = await _run(conn, llm)
        assert [t["title"] for t in tasks_repo.list_open(conn)] == ["buy milk"]
        assert reply == "Added: buy milk."
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_persistent_invented_claim_gets_an_honest_reply_and_nothing_is_created():
    conn = _conn()
    try:
        llm = _llm(_say("Task created!"), _say("Done, I added it."))
        reply = await _run(conn, llm)
        assert tasks_repo.list_open(conn) == []
        assert "haven't" in reply.lower() or "have not" in reply.lower()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_claim_after_a_real_tool_call_is_left_alone():
    conn = _conn()
    try:
        llm = _llm(_call("task_create", {"title": "call mum"}), _say("I've added the task: call mum."))
        reply = await _run(conn, llm)
        assert reply == "I've added the task: call mum."
        assert len(llm.calls) == 2
    finally:
        conn.close()
