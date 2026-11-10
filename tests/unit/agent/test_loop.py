"""Tests for agent/loop.py: scripted conversations and loop guards (plan §8.1)."""

import json
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from secretary.agent.loop import MAX_STEPS, run_turn
from secretary.agent.router import Router
from secretary.llm.base import LLMResponse, ToolCall
from secretary.llm.fake import FakeLLM
from secretary.llm.limiter import Limiter
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import tasks as tasks_repo
from secretary.tools.idempotency import idempotency_key
from secretary.tools.registry import Registry
from secretary.tools.tasks import register as register_tasks


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "loop.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


def _build_dependencies(conn):
    registry = Registry()
    register_tasks(registry)
    router = Router(registry)
    router.route("task_create", ["task", "create", "add", "remind"])
    router.route("task_list", ["task", "list", "show"])
    limiter = Limiter(rpm=10000, tpm=100000, safety=1.0, clock=time.monotonic)
    return registry, router, limiter


def _fake_llm(responses):
    fake = FakeLLM()
    for r in responses:
        fake.add(r)
    return fake


def _tool_call(name, args, call_id="c1"):
    return {"call_id": call_id, "name": name, "args": args}


@pytest.mark.asyncio
async def test_scripted_conversation_creates_task():
    conn = _conn()
    try:
        registry, router, limiter = _build_dependencies(conn)
        llm = _fake_llm(
            [
                LLMResponse(
                    text="",
                    tool_calls=[ToolCall(call_id="c1", name="task_create", args={"title": "submit the lab report", "when_text": "by Friday"})],
                    usage={},
                    headers={},
                    model="fake",
                ),
                LLMResponse(text="I've created the task to submit the lab report by Friday.", tool_calls=[], usage={}, headers={}, model="fake"),
            ]
        )
        ctx = {"turn_id": "turn-1", "now": "2026-11-07 10:00", "tz": "Asia/Kolkata", "today_iso": "2026-11-07"}
        result = await run_turn("add a task to submit the lab report by Friday", ctx, llm, limiter, router, registry, conn)
        assert "submit the lab report" in result or "task" in result.lower()
        # the task was persisted
        rows = tasks_repo.list_open(conn)
        assert any("lab report" in r["title"] for r in rows)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_loop_guard_hits_step_limit():
    conn = _conn()
    try:
        registry, router, limiter = _build_dependencies(conn)
        # LLM returns a fresh tool call every step (never deduped).
        responses = [
            LLMResponse(
                text="",
                tool_calls=[ToolCall(call_id=f"c{i}", name="task_create", args={"title": f"task {i}"})],
                usage={}, headers={}, model="fake",
            )
            for i in range(MAX_STEPS + 2)
        ]
        llm = _fake_llm(responses)
        ctx = {"turn_id": "turn-2", "now": "2026-11-07 10:00", "tz": "Asia/Kolkata", "today_iso": "2026-11-07"}
        result = await run_turn("keep adding tasks", ctx, llm, limiter, router, registry, conn)
        assert "step limit" in result.lower()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_no_tool_call_returns_text():
    conn = _conn()
    try:
        registry, router, limiter = _build_dependencies(conn)
        llm = _fake_llm(
            [LLMResponse(text="Sure thing!", tool_calls=[], usage={}, headers={}, model="fake")]
        )
        ctx = {"turn_id": "turn-3", "now": "2026-11-07 10:00", "tz": "Asia/Kolkata", "today_iso": "2026-11-07"}
        result = await run_turn("hello", ctx, llm, limiter, router, registry, conn)
        assert result == "Sure thing!"
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_tool_call_message_has_type_and_function_wrapper():
    """The assistant message that records a tool call must use the OpenAI-compatible
    shape {"id","type":"function","function":{"name","arguments"}} so providers
    (e.g. Groq) accept it. Regression test for the missing "type" 400.
    """
    conn = _conn()
    try:
        registry, router, limiter = _build_dependencies(conn)
        llm = _fake_llm(
            [
                LLMResponse(
                    text="",
                    tool_calls=[ToolCall(call_id="c1", name="task_create", args={"title": "buy milk"})],
                    usage={},
                    headers={},
                    model="fake",
                ),
                LLMResponse(text="Created the task.", tool_calls=[], usage={}, headers={}, model="fake"),
            ]
        )
        ctx = {"turn_id": "turn-wrap", "now": "2026-11-07 10:00", "tz": "Asia/Kolkata", "today_iso": "2026-11-07"}
        await run_turn("add a task buy milk", ctx, llm, limiter, router, registry, conn)
        # Inspect the last assistant message sent to the LLM.
        sent = llm.calls[-1]["messages"]
        assistant_tool_msgs = [m for m in sent if m.get("role") == "assistant" and m.get("tool_calls")]
        assert assistant_tool_msgs, "no assistant tool-call message was sent"
        for m in assistant_tool_msgs:
            for tc in m["tool_calls"]:
                assert tc.get("type") == "function", tc
                assert set(tc.keys()) == {"id", "type", "function"}, tc
                assert set(tc["function"].keys()) == {"name", "arguments"}, tc
                assert tc["function"]["name"] == "task_create"
                assert json.loads(tc["function"]["arguments"]) == {"title": "buy milk"}
    finally:
        conn.close()


def test_idempotency_key_stable():
    k1 = idempotency_key("turn-1", "task_create", {"title": "x"})
    k2 = idempotency_key("turn-1", "task_create", {"title": "x"})
    assert k1 == k2
