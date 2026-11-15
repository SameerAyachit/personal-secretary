"""MeteredClient: background LLM calls (research) share the chat rate-limit budget."""

from __future__ import annotations

from datetime import date

import pytest

from secretary.llm.base import LLMResponse
from secretary.llm.errors import DailyLimitReached
from secretary.llm.limiter import Limiter
from secretary.llm.metered import MeteredClient


class _Client:
    model = "m"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return LLMResponse(
            text="ok", tool_calls=[], usage={"total_tokens": 42}, headers={"x-ratelimit-remaining-tokens": "900"}, model="m"
        )

    async def list_models(self):
        return ["a"]

    async def aclose(self):
        self.closed = True


class _Limiter:
    def __init__(self) -> None:
        self.acquired: list[tuple[int, str]] = []
        self.reconciled: list[tuple] = []

    async def acquire(self, est, *, priority="background", on_wait=None):
        self.acquired.append((est, priority))

    def reconcile(self, used, est, header_remaining=None):
        self.reconciled.append((used, est, header_remaining))


@pytest.mark.asyncio
async def test_every_call_is_metered_at_background_priority():
    client, limiter = _Client(), _Limiter()
    metered = MeteredClient(client, limiter)
    resp = await metered.chat(
        messages=[{"role": "user", "content": "hello world " * 20}], max_tokens=50, temperature=0.1, purpose="research"
    )
    assert resp.text == "ok"
    (est, priority), = limiter.acquired
    assert priority == "background" and est > 20
    assert limiter.reconciled == [(42, est, "900")]
    assert client.calls[0]["purpose"] == "research"


@pytest.mark.asyncio
async def test_without_a_limiter_it_just_passes_through():
    client = _Client()
    metered = MeteredClient(client, None)
    await metered.chat(messages=[], max_tokens=5, temperature=0.0, purpose="p")
    assert len(client.calls) == 1
    assert metered.model == "m" and await metered.list_models() == ["a"]


@pytest.mark.asyncio
async def test_daily_limit_stops_the_call_before_it_reaches_the_provider():
    client = _Client()
    limiter = Limiter(rpm=0, tpm=0, safety=1.0, rpd=1, today=lambda: date(2026, 11, 15))
    metered = MeteredClient(client, limiter)
    await metered.chat(messages=[], max_tokens=5, temperature=0.0, purpose="p")
    with pytest.raises(DailyLimitReached):
        await metered.chat(messages=[], max_tokens=5, temperature=0.0, purpose="p")
    assert len(client.calls) == 1
