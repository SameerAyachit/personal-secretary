"""Tests for the research_brief pipeline (plan §14.3)."""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from secretary.integrations.fetch import FetchError
from secretary.integrations.search.provider import SearchResult, SearchUnavailable
from secretary.llm.base import LLMResponse
from secretary.llm.fake import FakeLLM
from secretary.llm.tokens import count_tokens
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import inbox as inbox_repo
from secretary.store.repos import research_briefs as briefs_repo
from secretary.tools.research import (
    ResearchBrief,
    check_claims,
    research_brief_tool,
    run_research_job,
)


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "r.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


class FakeSearchProvider:
    def __init__(self, results) -> None:
        self._results = results
        self.calls = 0

    def search(self, query: str, n: int = 5) -> list[SearchResult]:
        self.calls += 1
        return list(self._results)


class UnavailableProvider:
    def search(self, query: str, n: int = 5) -> list[SearchResult]:
        raise SearchUnavailable("down")


@pytest.mark.asyncio
async def test_research_brief_writes_sourced_brief(monkeypatch):
    fetched = {
        "https://example.com/a": "https://example.com/a\n\nQuantum computers use qubits to process information. Error correction is hard.",
        "https://example.com/b": "https://example.com/b\n\nError correction codes protect quantum states from noise.",
    }

    def fake_fetch(url: str) -> dict:
        return {"url": url, "text": fetched[url]}

    monkeypatch.setattr("secretary.tools.research.fetch_url", fake_fetch)

    provider = FakeSearchProvider([
        SearchResult(title="Source A", url="https://example.com/a", snippet="..."),
        SearchResult(title="Source B", url="https://example.com/b", snippet="..."),
    ])
    llm = FakeLLM([
        LLMResponse(text='{"queries": ["quantum computing", "error correction"]}', usage={}, headers={}, model="fake"),
        LLMResponse(
            text='{"summary": "Qubits process information.", "claims": [{"text": "quantum computers use qubits", "source_url": "https://example.com/a"}]}',
            usage={}, headers={}, model="fake",
        ),
        LLMResponse(
            text='{"summary": "Codes protect quantum states.", "claims": [{"text": "error correction protects states", "source_url": "https://example.com/b"}]}',
            usage={}, headers={}, model="fake",
        ),
        LLMResponse(
            text='{"brief": "Quantum computers use qubits [1](https://example.com/a). Error correction protects states [2](https://example.com/b)."}',
            usage={}, headers={}, model="fake",
        ),
        LLMResponse(text='{"keep": [0, 1]}', usage={}, headers={}, model="fake"),
    ])
    conn = _conn()
    try:
        conn.search_provider = provider
        conn.llm = llm
        result = await run_research_job(conn, "quantum computing")
        assert result["partial"] is False
        assert result["calls"] <= 8
        assert "qubits" in result["brief"].lower()
        assert "[1](https://example.com/a)" in result["brief"]
        assert "[2](https://example.com/b)" in result["brief"]
        assert [s["url"] for s in result["sources"]] == [
            "https://example.com/a",
            "https://example.com/b",
        ]
        assert provider.calls <= 2  # one search per planned query, deduplicated
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_research_brief_removes_unsupported_claims(monkeypatch):
    def fake_fetch(url: str) -> dict:
        return {"url": url, "text": "source text about " + url}

    monkeypatch.setattr("secretary.tools.research.fetch_url", fake_fetch)
    provider = FakeSearchProvider([
        SearchResult(title="A", url="https://example.com/a", snippet="..."),
    ])
    llm = FakeLLM([
        LLMResponse(text='{"queries": ["topic"]}', usage={}, headers={}, model="fake"),
        LLMResponse(
            text='{"summary": "S.", "claims": [{"text": "claimed fact", "source_url": "https://example.com/a"}]}',
            usage={}, headers={}, model="fake",
        ),
        LLMResponse(
            text='{"brief": "Supported sentence [1](https://example.com/a). Removed claim [9](https://example.com/a)."}',
            usage={}, headers={}, model="fake",
        ),
        LLMResponse(text='{"keep": [0]}', usage={}, headers={}, model="fake"),
    ])
    conn = _conn()
    try:
        conn.search_provider = provider
        conn.llm = llm
        result = await run_research_job(conn, "topic")
        assert result["partial"] is False
        assert "Supported sentence" in result["brief"]
        assert "Removed claim" not in result["brief"]
        assert "[9](https://example.com/a)" not in result["brief"]
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_research_brief_partial_when_search_unavailable(monkeypatch):
    def fake_fetch(url: str) -> dict:
        return {"url": url, "text": "x"}

    monkeypatch.setattr("secretary.tools.research.fetch_url", fake_fetch)

    llm = FakeLLM([])
    conn = _conn()
    try:
        conn.search_provider = UnavailableProvider()
        conn.llm = llm
        result = await run_research_job(conn, "topic")
        assert result["partial"] is True
        assert result["calls"] == 1
        assert result["sources"] == []
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_research_brief_partial_when_nothing_fetches(monkeypatch):
    def fetch_fails(url: str) -> dict:
        raise FetchError("blocked")

    monkeypatch.setattr("secretary.tools.research.fetch_url", fetch_fails)
    provider = FakeSearchProvider([
        SearchResult(title="A", url="https://example.com/a", snippet="..."),
    ])
    llm = FakeLLM([
        LLMResponse(text='{"queries": ["topic"]}', usage={}, headers={}, model="fake"),
        LLMResponse(
            text='{"summary": "S.", "claims": []}',
            usage={}, headers={}, model="fake",
        ),
    ])
    conn = _conn()
    try:
        conn.search_provider = provider
        conn.llm = llm
        result = await run_research_job(conn, "topic")
        assert result["partial"] is True
        assert result["sources"] == []
    finally:
        conn.close()


class _ClaimLLM:
    def __init__(self, keep) -> None:
        self._keep = keep
        self.calls = 0

    async def chat(self, *, messages, tools, max_tokens, temperature, purpose, **kwargs):
        self.calls += 1
        return LLMResponse(text='{"keep": ' + str(self._keep) + "}", usage={}, headers={}, model="fake")

    async def list_models(self) -> list[str]:
        return ["fake"]


@pytest.mark.asyncio
async def test_check_claims_removes_unsupported():
    llm = _ClaimLLM([0])
    cleaned = await check_claims(
        "Supported fact [1](https://example.com/a). Unsupported fabrication.",
        [{"url": "https://example.com/a"}],
        llm,
    )
    assert cleaned == "Supported fact [1](https://example.com/a)."
    assert "Unsupported fabrication" not in cleaned


@pytest.mark.asyncio
async def test_check_claims_empty_sources_returns_empty():
    cleaned = await check_claims("Any claim at all.", [], _ClaimLLM([0]))
    assert cleaned == ""


@pytest.mark.asyncio
async def test_check_claims_no_sentences():
    assert await check_claims("", [{"url": "https://example.com/a"}], _ClaimLLM([0])) == ""


@pytest.mark.asyncio
async def test_page_text_is_truncated_to_tokens_per_source(monkeypatch):
    seen: list[str] = []

    async def fake_summarize(self, url, text):
        seen.append(text)
        return {"summary": "s", "claims": []}

    monkeypatch.setattr(ResearchBrief, "_summarize", fake_summarize)
    monkeypatch.setattr(
        "secretary.tools.research.fetch_url", lambda url: {"url": url, "text": "word " * 5000}
    )
    pipeline = ResearchBrief(llm=None, search_provider=None, tokens_per_source=100, token_budget=10_000)
    await pipeline._gather([{"url": "https://e.com/a", "title": "a"}])
    assert count_tokens(seen[0]) <= 100


@pytest.mark.asyncio
async def test_token_budget_stops_further_sources(monkeypatch):
    async def fake_summarize(self, url, text):
        return {"summary": "s", "claims": []}

    monkeypatch.setattr(ResearchBrief, "_summarize", fake_summarize)
    monkeypatch.setattr(
        "secretary.tools.research.fetch_url", lambda url: {"url": url, "text": "word " * 5000}
    )
    sources = [{"url": f"https://e.com/{i}", "title": str(i)} for i in range(4)]
    pipeline = ResearchBrief(llm=None, search_provider=None, tokens_per_source=100, token_budget=250)
    sourced = await pipeline._gather(sources)
    assert len(sourced) == 2  # 100 + 100 fits, a third (300) would exceed 250


# ---- background job (plan §14.3) ------------------------------------------------------


def _script(*texts: str) -> FakeLLM:
    return FakeLLM([LLMResponse(text=t, usage={}, headers={}, model="fake") for t in texts])


_HAPPY = (
    '{"queries": ["topic"]}',
    '{"summary": "S.", "claims": []}',
    '{"brief": "A sentence [1](https://example.com/a)."}',
    '{"keep": [0]}',
)


def _happy_conn(monkeypatch):
    monkeypatch.setattr(
        "secretary.tools.research.fetch_url", lambda url: {"url": url, "text": "page text"}
    )
    conn = _conn()
    conn.search_provider = FakeSearchProvider([SearchResult("A", "https://example.com/a", "...")])
    conn.llm = _script(*_HAPPY)
    return conn


@pytest.mark.asyncio
async def test_job_records_the_brief_and_returns_its_id(monkeypatch):
    conn = _happy_conn(monkeypatch)
    result = await run_research_job(conn, "topic")
    row = conn.read(lambda c: briefs_repo.get(c, result["brief_id"]))
    assert (row["status"], row["topic"]) == ("done", "topic")
    assert "A sentence" in row["brief"]
    assert conn.read(lambda c: inbox_repo.list_by_status(c, None)) == []  # no inbox noise unless asked


@pytest.mark.asyncio
async def test_job_notifies_through_the_inbox_when_asked(monkeypatch):
    conn = _happy_conn(monkeypatch)
    await run_research_job(conn, "topic", notify=True)
    [item] = conn.read(lambda c: inbox_repo.list_by_status(c, None))
    assert item["kind"] == "system" and "topic" in item["title"]


@pytest.mark.asyncio
async def test_failed_job_is_recorded_and_reported_not_raised():
    conn = _conn()
    conn.search_provider = FakeSearchProvider([])

    class _Boom:
        async def chat(self, **kwargs):
            raise RuntimeError("provider down")

    conn.llm = _Boom()
    result = await run_research_job(conn, "topic", notify=True)
    assert "provider down" in result["error"]
    row = conn.read(lambda c: briefs_repo.get(c, result["brief_id"]))
    assert row["status"] == "failed" and "provider down" in row["error"]
    [item] = conn.read(lambda c: inbox_repo.list_by_status(c, None))
    assert "failed" in item["title"].lower()


@pytest.mark.asyncio
async def test_chat_tool_returns_immediately_and_the_job_finishes_in_background(monkeypatch):
    conn = _happy_conn(monkeypatch)
    started = await research_brief_tool(conn, "turn-1", {"topic": "topic"})
    assert started["status"] == "started" and "Research tab" in started["note"]
    [row] = conn.read(lambda c: briefs_repo.list_recent(c, 5))
    assert row["status"] in ("running", "done")
    await asyncio.gather(*conn.background_tasks)
    assert conn.read(lambda c: briefs_repo.get(c, row["id"]))["status"] == "done"
    assert len(conn.read(lambda c: inbox_repo.list_by_status(c, None))) == 1  # chat jobs notify


@pytest.mark.asyncio
async def test_chat_tool_without_an_llm_says_so():
    conn = _conn()
    conn.llm = None
    result = await research_brief_tool(conn, "turn-1", {"topic": "topic"})
    assert "LLM not configured" in result["error"]


@pytest.mark.asyncio
async def test_claim_check_counts_against_the_call_budget(monkeypatch):
    monkeypatch.setattr(
        "secretary.tools.research.fetch_url", lambda url: {"url": url, "text": "page text"}
    )
    llm = _script(*_HAPPY[:3])  # no 4th response: the claim check must not run
    pipeline = ResearchBrief(
        llm, FakeSearchProvider([SearchResult("A", "https://example.com/a", "...")]), max_calls=3
    )
    result = await pipeline.run("topic")
    assert result["calls"] == 3
    assert result["checked"] is False and "A sentence" in result["brief"]


@pytest.mark.asyncio
async def test_slow_fetch_does_not_block_the_event_loop(monkeypatch):
    def slow_fetch(url):
        time.sleep(0.4)
        return {"url": url, "text": "page text"}

    monkeypatch.setattr("secretary.tools.research.fetch_url", slow_fetch)
    pipeline = ResearchBrief(None, None)
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    async def fake_summarize(url, text):
        return {"summary": "s", "claims": []}

    pipeline._summarize = fake_summarize  # type: ignore[method-assign]
    beat = asyncio.create_task(heartbeat())
    await pipeline._gather([{"url": "https://e.com/a", "title": "a"}])
    beat.cancel()
    assert ticks >= 4
