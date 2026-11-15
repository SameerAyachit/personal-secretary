"""web_search must not block the shared worker event loop while the provider works."""

from __future__ import annotations

import asyncio
import time

import pytest

from secretary.integrations.search.provider import SearchResult, SearchUnavailable
from secretary.tools.search import web_search


class _Conn:
    def __init__(self, provider) -> None:
        self.search_provider = provider


class _SlowProvider:
    def search(self, query: str, n: int = 5):
        time.sleep(0.4)  # a blocking network call
        return [SearchResult("T", "https://example.com", "s")]


class _DownProvider:
    def search(self, query: str, n: int = 5):
        raise SearchUnavailable("breaker open")


@pytest.mark.asyncio
async def test_loop_keeps_running_during_a_slow_search():
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    beat = asyncio.create_task(heartbeat())
    result = await web_search(_Conn(_SlowProvider()), "t", {"query": "q"})
    beat.cancel()
    assert result["results"][0]["url"] == "https://example.com"
    assert ticks >= 4  # a blocked loop would have ticked ~0 times in 0.4 s


@pytest.mark.asyncio
async def test_unavailable_search_is_reported_not_raised():
    result = await web_search(_Conn(_DownProvider()), "t", {"query": "q"})
    assert result["status"] == "unavailable"
