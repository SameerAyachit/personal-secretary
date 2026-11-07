"""Fake LLM: scripted responses for tests and the FakeLLM contract (plan §7.1, §17)."""

from __future__ import annotations

from typing import Any

from .base import LLMClient, LLMResponse


class FakeLLM(LLMClient):
    """Returns scripted responses in order; useful for deterministic tests."""

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

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
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "purpose": purpose,
            }
        )
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(text="", tool_calls=[], usage={}, headers={}, model="fake")

    async def list_models(self) -> list[str]:
        return ["fake-model"]

    def add(self, response: LLMResponse) -> None:
        self._responses.append(response)
