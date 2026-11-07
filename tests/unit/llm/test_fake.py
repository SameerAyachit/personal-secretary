"""Tests for the FakeLLM (scripted responses for tests)."""

import pytest

from secretary.llm.base import LLMResponse, ToolCall
from secretary.llm.fake import FakeLLM


@pytest.mark.asyncio
async def test_fake_returns_scripted_responses_in_order():
    fake = FakeLLM(
        responses=[
            LLMResponse(text="first", tool_calls=[], usage={}, headers={}, model="fake"),
            LLMResponse(
                text="",
                tool_calls=[ToolCall(call_id="c1", name="tasks_add", args={"title": "x"})],
                usage={"total_tokens": 5},
                headers={},
                model="fake",
            ),
        ]
    )

    r1 = await fake.chat(messages=[], max_tokens=5, temperature=0.0, purpose="p")
    assert r1.text == "first"
    assert r1.tool_calls == []

    r2 = await fake.chat(messages=[], max_tokens=5, temperature=0.0, purpose="p")
    assert r2.text == ""
    assert len(r2.tool_calls) == 1
    assert r2.tool_calls[0].name == "tasks_add"
    assert r2.tool_calls[0].args == {"title": "x"}

    # Exhausted -> empty response.
    r3 = await fake.chat(messages=[], max_tokens=5, temperature=0.0, purpose="p")
    assert r3.text == ""
    assert r3.tool_calls == []


@pytest.mark.asyncio
async def test_fake_records_calls():
    fake = FakeLLM(
        responses=[LLMResponse(text="hi", tool_calls=[], usage={}, headers={}, model="fake")]
    )
    await fake.chat(
        messages=[{"role": "user", "content": "hello"}],
        tools=[{"name": "t"}],
        tool_choice="required",
        max_tokens=7,
        temperature=0.2,
        purpose="chat",
    )
    assert len(fake.calls) == 1
    assert fake.calls[0]["purpose"] == "chat"
    assert fake.calls[0]["max_tokens"] == 7
    assert fake.calls[0]["messages"][0]["content"] == "hello"


def test_fake_add_appends():
    fake = FakeLLM()
    fake.add(LLMResponse(text="a", tool_calls=[], usage={}, headers={}, model="fake"))
    assert len(fake._responses) == 1
