"""OpenAI-compatible LLM client (Groq, Gemini compat, OpenRouter, Ollama).

Uses ``httpx`` async client. POSTs to ``{base_url}/chat/completions`` and
normalises the response into :class:`~secretary.llm.base.LLMResponse`.
Rate-limit headers (``x-ratelimit-*``, ``retry-after``) are surfaced so the
limiter can reconcile (plan §7.4).

The :class:`httpx.AsyncClient` is created lazily on the running event loop in
:meth:`_ensure_client`, so all HTTP calls happen on the same asyncio loop that
the agent worker owns (plan §3.1). This keeps the shared connection pool bound
to one loop and avoids ``SQLite objects created in a thread`` / event-loop
mismatch errors when turns are submitted from the Qt thread.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from .base import LLMClient, LLMResponse, ToolCall, parse_tool_args
from .errors import AuthError, ProviderUnavailable, RequestTooLarge

_CHAT_PATH = "/chat/completions"
_MODELS_PATH = "/models"


class OpenAICompatClient(LLMClient):
    """An OpenAI-compatible chat-completions client for a single model."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
        reasoning_effort: str = "",
    ) -> None:
        self.reasoning_effort = reasoning_effort
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        # Created lazily on the running (worker) loop in _ensure_client so the
        # shared httpx connection pool stays bound to the worker event loop
        # (plan §3.1). All chat()/list_models() calls run on that loop.
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

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
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if self.reasoning_effort:
            # gpt-oss on Groq: low | medium | high (Groq docs, "Reasoning").
            body["reasoning_effort"] = self.reasoning_effort
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
            body["tool_choice"] = tool_choice

        start = time.monotonic()
        try:
            client = await self._ensure_client()
            resp = await client.post(_CHAT_PATH, json=body)
        except httpx.RequestError as exc:
            raise ProviderUnavailable(f"provider request failed: {exc}") from exc

        if resp.status_code == 413:
            raise RequestTooLarge("request larger than the provider accepts")
        if resp.status_code in (401, 403):
            raise AuthError(
                "The AI provider rejected the API key. "
                "Open Settings > AI and enter a valid key."
            )
        if resp.status_code >= 400:
            raise ProviderUnavailable(
                f"provider returned {resp.status_code}: {resp.text[:200]}"
            )

        data = resp.json()
        latency_ms = time.monotonic() - start
        return self._normalise(data, latency_ms, dict(resp.headers))

    async def list_models(self) -> list[str]:
        try:
            client = await self._ensure_client()
            resp = await client.get(_MODELS_PATH)
        except httpx.RequestError as exc:
            raise ProviderUnavailable(f"list_models failed: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderUnavailable(
                f"list_models returned {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        return [item.get("id", "") for item in data.get("data", []) if item.get("id")]

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _normalise(self, data: dict, latency_ms: float, headers: dict) -> LLMResponse:
        choices = data.get("choices", []) or []
        choice = choices[0] if choices else {}
        message = choice.get("message", {}) or {}
        text = message.get("content") or ""
        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls", []) or []:
            fn = tc.get("function", {}) or {}
            tool_calls.append(
                ToolCall(
                    call_id=tc.get("id", ""),
                    name=fn.get("name", ""),
                    args=parse_tool_args(fn.get("arguments")),
                )
            )
        usage = data.get("usage", {}) or {}
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            usage={
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            headers=headers,
            model=data.get("model", self.model),
            latency_ms=latency_ms,
            finish_reason=choice.get("finish_reason", "") or "",
        )
