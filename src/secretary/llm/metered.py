"""LLM client wrapper that charges every call to the shared rate limiter (plan §7.4).

The agent loop already meters its own calls. Background work (research briefs)
used to call the raw client and bypass the limiter, so it could burn the whole
per-minute budget and starve chat. ``MeteredClient`` gives such work the same
budget at ``background`` priority, which yields to interactive turns.
"""

from __future__ import annotations

from typing import Any

from secretary.llm.base import LLMResponse
from secretary.llm.limiter import Limiter
from secretary.llm.tokens import count_tokens


def _estimate(messages: list[dict], tools: list[dict] | None) -> int:
    total = sum(count_tokens(str(m.get("content", ""))) for m in messages)
    total += sum(count_tokens(str(t)) for t in tools or [])
    return total


class MeteredClient:
    """Same ``chat``/``list_models`` surface as the wrapped client."""

    def __init__(self, client: Any, limiter: Limiter | None, priority: str = "background") -> None:
        self._client = client
        self._limiter = limiter
        self._priority = priority

    def __getattr__(self, name: str) -> Any:  # model, base_url, aclose, ...
        return getattr(self._client, name)

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
        est = _estimate(messages, tools)
        if self._limiter is not None:
            await self._limiter.acquire(est, priority=self._priority)
        resp = await self._client.chat(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            max_tokens=max_tokens,
            temperature=temperature,
            purpose=purpose,
        )
        if self._limiter is not None:
            self._limiter.reconcile(
                resp.usage.get("total_tokens", 0), est, resp.headers.get("x-ratelimit-remaining-tokens")
            )
        return resp

    async def list_models(self) -> list[str]:
        return await self._client.list_models()
