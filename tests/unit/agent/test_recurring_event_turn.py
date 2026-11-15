"""Regression: "set a task on my calendar ... every day, 4pm to 6pm" typed at 21:26.

Live eval hit "I've reached the step limit": today's 4pm had passed, the tool error was
unreadable and the model kept retrying. The turn must now end with a real answer.
"""

from __future__ import annotations

import sqlite3
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

import secretary.tools.events as events_tools
from secretary.agent.loop import run_turn
from secretary.agent.wiring import build_registry_and_router
from secretary.llm.base import LLMResponse, ToolCall
from secretary.llm.fake import FakeLLM
from secretary.llm.limiter import Limiter
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate

NOW = datetime(2026, 11, 15, 15, 56, tzinfo=UTC)  # 21:26 IST
UTTERANCE = ("set a task on my calendar to focus on the course i have taken up for at least "
             "2 hours a day, that is, 4 pm to 6 pm")


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "r.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


def _call(args: dict, call_id: str) -> LLMResponse:
    return LLMResponse(text="", tool_calls=[ToolCall(call_id=call_id, name="event_create", args=args)],
                       usage={}, headers={}, model="fake")


def _say(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=[], usage={}, headers={}, model="fake")


async def _run(conn, llm) -> str:
    registry, router = build_registry_and_router()
    ctx = {"turn_id": "t1", "now": "2026-11-15T21:26:00+05:30", "tz": "Asia/Kolkata",
           "today_iso": "2026-11-15"}
    limiter = Limiter(rpm=10000, tpm=100000, safety=1.0, clock=time.monotonic)
    return await run_turn(UTTERANCE, ctx, llm, limiter, router, registry, conn)


def _event_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM events WHERE deleted_at IS NULL").fetchone()[0]


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(events_tools, "_utc_now", lambda: NOW)


@pytest.mark.asyncio
async def test_model_recovers_from_the_past_time_hint_and_creates_a_daily_series():
    conn = _conn()
    try:
        llm = FakeLLM()
        # 1st try: the model asks for a one-off "today 4pm" -> past -> plain hint.
        llm.add(_call({"title": "Focus on course", "when_text": "today 4pm", "duration_text": "2 hours"}, "c1"))
        # 2nd try follows the hint and makes it repeat.
        llm.add(_call({"title": "Focus on course", "when_text": "4pm", "duration_text": "2 hours",
                       "recurrence_text": "every day"}, "c2"))
        llm.add(_say("Done: Focus on course is on your calendar every day, 4-6pm, from tomorrow."))
        reply = await _run(conn, llm)
        assert "every day" in reply
        assert "step limit" not in reply.lower()
        assert _event_count(conn) >= 29
        tool_msgs = [m["content"] for m in llm.calls[1]["messages"] if m.get("role") == "tool"]
        assert "already in the past" in tool_msgs[0]  # the model was told why, in words
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_model_that_keeps_failing_gets_the_real_reason_not_the_step_limit():
    conn = _conn()
    try:
        llm = FakeLLM()
        for i in range(8):
            llm.add(_call({"title": "Focus", "when_text": f"today 4pm v{i}", "duration_text": "2 hours"}, f"c{i}"))
        reply = await _run(conn, llm)
        assert "step limit" not in reply.lower()
        assert "tomorrow" in reply.lower() or "understand" in reply.lower()
        assert _event_count(conn) == 0
    finally:
        conn.close()
