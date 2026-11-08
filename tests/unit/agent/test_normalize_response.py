"""Tests for agent/normalize_response.py (plan §8.1, Appendix C)."""

import json

from secretary.agent.normalize_response import normalize_response
from secretary.llm.base import LLMResponse, ToolCall


def _resp(text, tool_calls=None, finish_reason="stop"):
    return LLMResponse(
        text=text,
        tool_calls=[ToolCall(**tc) for tc in (tool_calls or [])],
        usage={},
        headers={},
        model="m",
        finish_reason=finish_reason,
    )


def test_provider_structured_tool_calls_pass_through():
    resp = _resp("hello", tool_calls=[{"call_id": "c1", "name": "task_create", "args": {"title": "x"}}])
    out = normalize_response(resp, allowed_tools={"task_create"})
    assert len(out.tool_calls) == 1
    assert out.tool_calls[0].name == "task_create"
    assert out.tool_calls[0].args == {"title": "x"}


def test_unknown_tool_filtered():
    resp = _resp("", tool_calls=[{"call_id": "c1", "name": "nonexistent_tool", "args": {}}])
    out = normalize_response(resp, allowed_tools={"task_create"})
    assert out.tool_calls == []


def test_tool_call_json_in_content():
    resp = _resp('{"name": "task_create", "arguments": {"title": "buy milk"}}')
    out = normalize_response(resp, allowed_tools={"task_create"})
    assert len(out.tool_calls) == 1
    assert out.tool_calls[0].name == "task_create"
    assert out.tool_calls[0].args == {"title": "buy milk"}


def test_fenced_json():
    resp = _resp('Here you go\n```json\n{"name": "task_list", "arguments": {"filter": "open"}}\n```\nDone.')
    out = normalize_response(resp, allowed_tools={"task_list"})
    assert len(out.tool_calls) == 1
    assert out.tool_calls[0].name == "task_list"
    assert out.tool_calls[0].args == {"filter": "open"}


def test_args_as_string_parsed():
    args_str = json.dumps({"title": "drink water", "when_text": "in 20 min"})
    text = json.dumps({"name": "reminder_create", "arguments": args_str})
    resp = _resp(text)
    out = normalize_response(resp, allowed_tools={"reminder_create"})
    assert len(out.tool_calls) == 1
    assert out.tool_calls[0].name == "reminder_create"
    assert out.tool_calls[0].args == {"title": "drink water", "when_text": "in 20 min"}


def test_duplicate_calls_deduped():
    resp = _resp(
        '{"name": "task_create", "arguments": {"title": "x"}}\n'
        '{"name": "task_create", "arguments": {"title": "x"}}'
    )
    out = normalize_response(resp, allowed_tools={"task_create"})
    assert len(out.tool_calls) == 1


def test_trailing_prose_kept():
    resp = _resp('I will do that. {"name": "task_create", "arguments": {"title": "x"}}')
    out = normalize_response(resp, allowed_tools={"task_create"})
    assert len(out.tool_calls) == 1
    assert out.text == 'I will do that. {"name": "task_create", "arguments": {"title": "x"}}'


def test_empty_content_no_calls():
    resp = _resp("")
    out = normalize_response(resp, allowed_tools={"task_create"})
    assert out.tool_calls == []
    assert out.text == ""
