"""Search provider interface and a DuckDuckGo (ddgs) implementation with a circuit
breaker and a configurable-TTL SQLite cache (plan §14.1).

Search results are untrusted (plan §14.1 / §8.6): titles and snippets are treated
as data, never as instructions.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Protocol

import ddgs

from secretary.store.repos import search_cache as cache_repo


class SearchUnavailable(Exception):
    """Raised when search cannot be performed (provider down / breaker open)."""


class SearchResult:
    """A single search result."""

    def __init__(self, title: str, url: str, snippet: str) -> None:
        self.title = title
        self.url = url
        self.snippet = snippet

    def to_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


class SearchProvider(Protocol):
    def search(self, query: str, n: int = 5) -> list[SearchResult]:
        ...


class DDGSSearchProvider(SearchProvider):
    """DuckDuckGo HTML search via ddgs."""

    def search(self, query: str, n: int = 5) -> list[SearchResult]:
        results: list[SearchResult] = []
        with ddgs.DDGS() as ddgs_client:
            for r in ddgs_client.text(query, max_results=n):
                results.append(
                    SearchResult(
                        title=r.get("title", ""),
                        url=r.get("link", ""),
                        snippet=r.get("snippet", ""),
                    )
                )
        return results


class CircuitBreaker:
    """Opens after N consecutive failures for a cooldown window."""

    def __init__(self, failures: int = 3, open_minutes: int = 10) -> None:
        self.failures = failures
        self.open_minutes = open_minutes
        self._consecutive = 0
        self._opened_at: float | None = None

    def record_success(self) -> None:
        self._consecutive = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive += 1
        if self._consecutive >= self.failures:
            self._opened_at = time.time()

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.time() - self._opened_at > self.open_minutes * 60:
            self._opened_at = None
            self._consecutive = 0
            return False
        return True

    def record_call(self, ok: bool) -> None:
        if ok:
            self.record_success()
        else:
            self.record_failure()


class SearchCache:
    """SQLite-backed cache keyed by a normalised query hash with a TTL.

    The ``search_cache`` table comes from migration 003. Writes go through
    :meth:`store.db.Connection.write` (BEGIN IMMEDIATE / COMMIT under the
    writer lock); the store connection is autocommit (plan §5.4).
    """

    def __init__(self, con, ttl_hours: int = 24) -> None:
        self._con = con
        self._ttl = timedelta(hours=ttl_hours)

    def _key(self, query: str) -> str:
        return hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()

    def get(self, query: str) -> list[SearchResult] | None:
        cutoff = (datetime.now(UTC) - self._ttl).strftime("%Y-%m-%dT%H:%M:%SZ")
        raw = self._con.read(lambda c: cache_repo.get(c, self._key(query), cutoff))
        if raw is None:
            return None
        return [SearchResult(**r) for r in json.loads(raw)]

    def set(self, query: str, results: list[SearchResult]) -> None:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = json.dumps([r.to_dict() for r in results])
        self._con.write(lambda c: cache_repo.put(c, self._key(query), query, payload, now))


class SearchService:
    """Search with circuit breaker + cache."""

    def __init__(
        self, con, provider: SearchProvider, breaker: CircuitBreaker, cache_hours: int = 24
    ) -> None:
        self._con = con
        self._provider = provider
        self._breaker = breaker
        self._cache = SearchCache(con, cache_hours)

    def search(self, query: str, n: int = 5) -> list[SearchResult]:
        cached = self._cache.get(query)
        if cached is not None:
            return cached
        if self._breaker.is_open():
            raise SearchUnavailable("search provider circuit breaker is open")
        try:
            results = self._provider.search(query, n)
        except Exception as exc:
            self._breaker.record_call(False)
            raise SearchUnavailable(str(exc)) from exc
        self._breaker.record_call(True)
        self._cache.set(query, results)
        return results
