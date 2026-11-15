"""A failing tool must end the turn with the real reason, not a generic 'step limit'."""

from __future__ import annotations

import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from secretary.agent.loop import run_turn
from secretary.agent.router import Router
from secretary.llm.base import LLMResponse, ToolCall
from secretary.llm.fake import FakeLLM
from secretary.llm.limiter import Limiter
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.tools.registry import Registry, SafetyClass, ToolSpec


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "f.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


def _call(args: dict, call_id: str = "c1") -> LLMResponse:
    return LLMResponse(text="", tool_calls=[ToolCall(call_id=call_id, name="event_create", args=args)],
                       usage={}, headers={}, model="fake")


def _say(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=[], usage={}, headers={}, model="fake")


def _registry(fn) -> Registry:
    registry = Registry()
    registry.register(ToolSpec(
        name="event_create", description="make an event", group="calendar",
        safety_class=SafetyClass.B, args_model=None, fn=fn,
    ))
    return registry


async def _run(registry, llm) -> str:
    ctx = {"turn_id": "t1", "now": "2026-11-15T21:26:00+05:30", "tz": "Asia/Kolkata",
           "today_iso": "2026-11-15"}
    limiter = Limiter(rpm=10000, tpm=100000, safety=1.0, clock=time.monotonic)
    return await run_turn("set an event on my calendar at 4pm", ctx, llm, limiter,
                          Router(registry), registry, _conn())


@pytest.mark.asyncio
async def test_two_failures_in_a_row_report_the_real_reason():
    calls = []

    def fn(conn, turn_id, args):
        calls.append(args)
        return {"error": "model-only text", "user_message": "That time has already passed today."}

    llm = FakeLLM()
    for i in range(6):
        llm.add(_call({"title": "Focus", "when_text": f"4pm try {i}"}, f"c{i}"))
    reply = await _run(_registry(fn), llm)
    assert "already passed" in reply
    assert "step limit" not in reply.lower()
    assert len(calls) == 2  # stopped early, did not burn every step


@pytest.mark.asyncio
async def test_a_single_failure_lets_the_model_recover():
    def fn(conn, turn_id, args):
        if args["when_text"] == "4pm":
            return {"error": "past", "user_message": "That time has already passed today."}
        return {"event_id": 1, "title": args["title"]}

    llm = FakeLLM()
    llm.add(_call({"title": "Focus", "when_text": "4pm"}, "c1"))
    llm.add(_call({"title": "Focus", "when_text": "tomorrow 4pm"}, "c2"))
    llm.add(_say("Done, Focus is on your calendar tomorrow at 4pm."))
    reply = await _run(_registry(fn), llm)
    assert "tomorrow" in reply.lower()


@pytest.mark.asyncio
async def test_unexpected_exception_is_reported_plainly():
    def fn(conn, turn_id, args):
        raise RuntimeError("disk is on fire")

    llm = FakeLLM()
    for i in range(4):
        llm.add(_call({"title": "Focus", "when_text": f"x{i}"}, f"c{i}"))
    reply = await _run(_registry(fn), llm)
    assert "disk is on fire" in reply
    assert "tool event_create failed" not in reply
