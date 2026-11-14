"""Tests for OpenAICompatClient using mocked HTTP (respx)."""

import json

import pytest
import respx
from httpx import Response

from secretary.llm.errors import AuthError, ProviderUnavailable, RequestTooLarge
from secretary.llm.openai_compat import OpenAICompatClient

BASE = "https://api.groq.com/openai/v1"


def _chat_response(tool_calls=None, finish_reason="stop", text="ok", model="m"):
    message = {"role": "assistant", "content": text}
    if tool_calls:
        message["tool_calls"] = [
            {"id": f"call_{i}", "type": "function", "function": tc} for i, tc in enumerate(tool_calls)
        ]
    return {
        "id": "chatcmpl-1",
        "model": model,
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


@pytest.mark.asyncio
async def test_chat_normalises_tool_calls():
    with respx.mock:
        respx.post(f"{BASE}/chat/completions").mock(
            return_value=Response(200, json=_chat_response(
                tool_calls=[{"name": "tasks_add", "arguments": '{"title": "buy milk"}'}],
                text=None,
                finish_reason="tool_calls",
            ))
        )
        client = OpenAICompatClient(base_url=BASE, api_key="k", model="m")
        try:
            resp = await client.chat(
                messages=[{"role": "user", "content": "add a task"}],
                tools=[{"name": "tasks_add"}],
                tool_choice="auto",
                max_tokens=100,
                temperature=0.1,
                purpose="chat",
            )
        finally:
            await client.aclose()
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].call_id == "call_0"
    assert resp.tool_calls[0].name == "tasks_add"
    assert resp.tool_calls[0].args == {"title": "buy milk"}
    assert resp.finish_reason == "tool_calls"
    assert resp.usage["total_tokens"] == 15


@pytest.mark.asyncio
async def test_chat_plain_text():
    with respx.mock:
        respx.post(f"{BASE}/chat/completions").mock(
            return_value=Response(200, json=_chat_response(text="hello world"))
        )
        client = OpenAICompatClient(base_url=BASE, api_key="k", model="m")
        try:
            resp = await client.chat(messages=[], max_tokens=10, temperature=0.0, purpose="p")
        finally:
            await client.aclose()
    assert resp.text == "hello world"
    assert resp.tool_calls == []


@pytest.mark.asyncio
async def test_413_raises_request_too_large():
    with respx.mock:
        respx.post(f"{BASE}/chat/completions").mock(return_value=Response(413, text="too large"))
        client = OpenAICompatClient(base_url=BASE, api_key="k", model="m")
        try:
            with pytest.raises(RequestTooLarge):
                await client.chat(messages=[], max_tokens=10, temperature=0.0, purpose="p")
        finally:
            await client.aclose()


@pytest.mark.asyncio
async def test_4xx_raises_provider_unavailable():
    with respx.mock:
        respx.post(f"{BASE}/chat/completions").mock(
            return_value=Response(401, json={"error": {"message": "bad key"}})
        )
        client = OpenAICompatClient(base_url=BASE, api_key="k", model="m")
        try:
            with pytest.raises(ProviderUnavailable):
                await client.chat(messages=[], max_tokens=10, temperature=0.0, purpose="p")
        finally:
            await client.aclose()


@pytest.mark.asyncio
async def test_network_error_raises_provider_unavailable():
    client = OpenAICompatClient(base_url="http://127.0.0.1:1", api_key="k", model="m")
    try:
        with pytest.raises(ProviderUnavailable):
            await client.chat(messages=[], max_tokens=10, temperature=0.0, purpose="p")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_list_models():
    with respx.mock:
        respx.get(f"{BASE}/models").mock(
            return_value=Response(200, json={"data": [{"id": "m1"}, {"id": "m2"}]})
        )
        client = OpenAICompatClient(base_url=BASE, api_key="k", model="m")
        try:
            models = await client.list_models()
        finally:
            await client.aclose()
    assert models == ["m1", "m2"]


@pytest.mark.asyncio
async def test_missing_type_in_assistant_tool_call_returns_400():
    """A provider enforcing the OpenAI tool_call shape rejects messages whose
    assistant tool_call entries lack "type" (the Groq 400 we saw in production).
    """
    with respx.mock:

        def check(request):
            body = json.loads(request.content)
            for m in body.get("messages", []):
                if m.get("role") == "assistant":
                    for tc in m.get("tool_calls", []) or []:
                        if tc.get("type") != "function":
                            return Response(
                                400,
                                json={
                                    "error": {
                                        "message": "messages.2.tool_calls.0.type: property 'type' is missing",
                                        "type": "invalid_request_error",
                                    }
                                },
                            )
            return Response(200, json=_chat_response(text="ok"))

        respx.post(f"{BASE}/chat/completions").mock(side_effect=check)
        client = OpenAICompatClient(base_url=BASE, api_key="k", model="m")
        try:
            with pytest.raises(ProviderUnavailable) as exc:
                await client.chat(
                    messages=[
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {"id": "c1", "name": "task_create", "arguments": '{"title": "x"}'}
                            ],
                        }
                    ],
                    tools=[{"name": "task_create"}],
                    tool_choice="auto",
                    max_tokens=100,
                    temperature=0.1,
                    purpose="tool",
                )
            assert "type" in str(exc.value) and "missing" in str(exc.value)
        finally:
            await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_auth_failure_raises_auth_error(status):
    with respx.mock:
        respx.post(f"{BASE}/chat/completions").mock(
            return_value=Response(status, json={"error": {"message": "Invalid API Key"}})
        )
        client = OpenAICompatClient(base_url=BASE, api_key="k", model="m")
        try:
            with pytest.raises(AuthError, match="Settings"):
                await client.chat(messages=[], max_tokens=10, temperature=0.0, purpose="p")
        finally:
            await client.aclose()
    assert issubclass(AuthError, ProviderUnavailable)


@pytest.mark.asyncio
@pytest.mark.parametrize("effort,expected", [("low", "low"), ("", None)])
async def test_reasoning_effort_is_sent_only_when_set(effort, expected):
    with respx.mock:
        route = respx.post(f"{BASE}/chat/completions").mock(
            return_value=Response(200, json=_chat_response())
        )
        client = OpenAICompatClient(
            base_url=BASE, api_key="k", model="openai/gpt-oss-120b", reasoning_effort=effort
        )
        try:
            await client.chat(messages=[], max_tokens=10, temperature=0.0, purpose="p")
        finally:
            await client.aclose()
    sent = json.loads(route.calls.last.request.content)
    assert sent.get("reasoning_effort") == expected
