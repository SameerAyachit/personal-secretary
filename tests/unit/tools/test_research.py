"""Tests for the research_brief pipeline (plan §14.3)."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from secretary.integrations.fetch import FetchError
from secretary.integrations.search.provider import SearchResult, SearchUnavailable
from secretary.llm.base import LLMResponse
from secretary.llm.fake import FakeLLM
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.tools.research import check_claims, research_brief_tool


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
        result = await research_brief_tool(conn, "turn-1", {"topic": "quantum computing"})
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
        result = await research_brief_tool(conn, "turn-1", {"topic": "topic"})
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
        result = await research_brief_tool(conn, "turn-1", {"topic": "topic"})
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
        result = await research_brief_tool(conn, "turn-1", {"topic": "topic"})
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
