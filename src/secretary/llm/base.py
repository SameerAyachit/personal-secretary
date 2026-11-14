"""LLM provider interface and shared response model (plan §7.1).

The LLM is behind a provider interface so the runtime model can be swapped
without touching the agent. All implementations are async; the agent worker
owns the event loop and calls through ``run_coroutine_threadsafe``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


def parse_tool_args(value) -> dict:
    """Tool-call arguments as a dict: accepts a dict or a JSON object string;
    anything else (including malformed JSON) becomes ``{}``."""
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


@dataclass
class ToolCall:
    """A single tool call returned by the model."""

    call_id: str
    name: str
    args: dict


@dataclass
class LLMResponse:
    """A normalised response from any LLM provider."""

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)
    model: str = ""
    latency_ms: float = 0.0
    finish_reason: str = ""


@runtime_checkable
class LLMClient(Protocol):
    """Provider interface. Implementations: OpenAICompatClient, FakeLLM."""

    async def chat(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        max_tokens: int,
        temperature: float,
        purpose: str,
    ) -> LLMResponse:
        ...

    async def list_models(self) -> list[str]:
        ...
