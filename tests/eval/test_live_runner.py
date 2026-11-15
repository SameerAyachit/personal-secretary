"""The live eval runner, driven by a FakeLLM (no network, no key)."""

from __future__ import annotations

import pytest
from tests.eval.cases import CASES
from tests.eval.live import run_live

from secretary.config import load_config
from secretary.llm.base import LLMResponse, ToolCall
from secretary.llm.fake import FakeLLM


def _call(name: str, args: dict) -> LLMResponse:
    return LLMResponse(text="", tool_calls=[ToolCall(call_id="c1", name=name, args=args)],
                       usage={}, headers={}, model="fake")


@pytest.mark.asyncio
async def test_runner_scores_with_the_real_tool_names_and_schemas():
    cases = [c for c in CASES if c.id in {"create-2", "query-2", "event-recur-1"}]
    llm = FakeLLM()
    llm.add(_call("task_create", {"title": "call the dentist", "when_text": "tomorrow"}))
    llm.add(_call("task_list", {"filter": "today"}))
    llm.add(_call("event_create", {"title": "Focus", "when_text": "4pm", "recurrence_text": "every day"}))
    results = await run_live(llm, cases, load_config(), delay=0)
    assert [r.passed for r in results] == [True, True, True]
    # The model really was offered the app's tool schemas, with no time zone argument.
    offered = {s["name"] for s in llm.calls[2]["tools"]}
    assert "event_create" in offered
    assert all("tz" not in (s.get("parameters", {}).get("properties", {})) for s in llm.calls[2]["tools"])


@pytest.mark.asyncio
async def test_runner_fails_a_one_off_event_for_a_repeating_request():
    case = next(c for c in CASES if c.id == "event-recur-1")
    llm = FakeLLM()
    llm.add(_call("event_create", {"title": "Focus", "when_text": "today 4pm"}))
    results = await run_live(llm, [case], load_config(), delay=0)
    assert [r.passed for r in results] == [False]
