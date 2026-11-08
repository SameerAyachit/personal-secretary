"""normalize_response: turn raw model output into text + tool calls (plan §8.1, Appendix C).

Handles every malformed shape small models emit:
  * tool-call JSON in ``content``
  * fenced JSON (```json ... ```)
  * multiple calls, including duplicates (deduplicated)
  * unknown tool names (dropped)
  * ``arguments``/``args`` as a string instead of an object
  * trailing prose after the call
  * empty content with no calls
"""

from __future__ import annotations

import json
import re

from secretary.llm.base import LLMResponse, ToolCall

_FENCED = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL | re.IGNORECASE)
_DECODER = json.JSONDecoder()


def _parse_args(value) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _candidate_objects(text: str) -> list:
    """Extract JSON object(s) from fenced blocks or embedded bare objects."""
    candidates: list = []
    for m in _FENCED.finditer(text):
        candidates.append(m.group(1).strip())
    # Scan for embedded ``{...}`` objects (handles trailing prose).
    idx = text.find("{")
    while idx != -1:
        try:
            obj, end = _DECODER.raw_decode(text, idx)
            candidates.append(obj)
            idx = text.find("{", end)
        except json.JSONDecodeError:
            idx = text.find("{", idx + 1)
    return candidates


def normalize_response(
    resp: LLMResponse, allowed_tools: set[str] | None = None
) -> LLMResponse:
    """Normalise an LLM response into ``text`` + ``tool_calls``.

    Provider-structured ``tool_calls`` are passed through (unknown tools
    filtered). Otherwise the text is scanned for tool-call JSON.
    """
    if resp.tool_calls:
        calls = [
            tc
            for tc in resp.tool_calls
            if allowed_tools is None or tc.name in allowed_tools
        ]
        return LLMResponse(
            text=resp.text or "",
            tool_calls=calls,
            usage=dict(resp.usage),
            headers=dict(resp.headers),
            model=resp.model,
            latency_ms=resp.latency_ms,
            finish_reason=resp.finish_reason,
        )

    text = resp.text or ""
    calls: list[ToolCall] = []
    seen: set[tuple[str, str]] = set()

    for cand in _candidate_objects(text):
        if isinstance(cand, str):
            try:
                obj = json.loads(cand)
            except json.JSONDecodeError:
                continue
        else:
            obj = cand
        items = obj if isinstance(obj, list) else [obj] if isinstance(obj, dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("tool")
            args = _parse_args(item.get("arguments", item.get("args", {})))
            call_id = item.get("id") or item.get("call_id") or ""
            if not name:
                continue
            if allowed_tools is not None and name not in allowed_tools:
                continue
            dedupe_key = (name, json.dumps(args, sort_keys=True))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            calls.append(ToolCall(call_id=call_id, name=name, args=args))

    return LLMResponse(
        text=text,
        tool_calls=calls,
        usage=dict(resp.usage),
        headers=dict(resp.headers),
        model=resp.model,
        latency_ms=resp.latency_ms,
        finish_reason=resp.finish_reason,
    )
