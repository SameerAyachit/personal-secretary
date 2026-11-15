"""DDGS provider: real ddgs result keys (href/body), 'no results' is not a failure."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import ClassVar

import pytest
from ddgs.exceptions import DDGSException

import secretary.integrations.search.provider as provider_module
from secretary.integrations.search.provider import (
    CircuitBreaker,
    DDGSSearchProvider,
    SearchService,
)
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate


class _FakeDDGS:
    """Stands in for ``ddgs.DDGS``; returns what ddgs 9.x really returns."""

    rows: ClassVar[list[dict]] = []
    error: ClassVar[Exception | None] = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def text(self, query: str, max_results: int = 5):
        if self.error is not None:
            raise self.error
        return list(self.rows)


@pytest.fixture
def fake_ddgs(monkeypatch):
    _FakeDDGS.rows = []
    _FakeDDGS.error = None
    monkeypatch.setattr(provider_module.ddgs, "DDGS", _FakeDDGS)
    return _FakeDDGS


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "s.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


def test_results_use_href_and_body(fake_ddgs):
    fake_ddgs.rows = [{"title": "T", "href": "https://example.com/a", "body": "snippet text"}]
    [result] = DDGSSearchProvider().search("q", 3)
    assert (result.title, result.url, result.snippet) == ("T", "https://example.com/a", "snippet text")


def test_rows_without_a_url_are_skipped(fake_ddgs):
    fake_ddgs.rows = [{"title": "no url", "body": "x"}, {"title": "ok", "href": "https://e.com", "body": ""}]
    assert [r.url for r in DDGSSearchProvider().search("q", 3)] == ["https://e.com"]


def test_no_results_is_an_empty_list_not_an_error(fake_ddgs):
    fake_ddgs.error = DDGSException("No results found.")
    assert DDGSSearchProvider().search("q", 3) == []


def test_other_ddgs_errors_still_propagate(fake_ddgs):
    fake_ddgs.error = DDGSException("Timeout while connecting")
    with pytest.raises(DDGSException):
        DDGSSearchProvider().search("q", 3)


def test_empty_results_do_not_trip_the_breaker_or_fill_the_cache(fake_ddgs):
    fake_ddgs.error = DDGSException("No results found.")
    breaker = CircuitBreaker(failures=2, open_minutes=10)
    service = SearchService(_conn(), DDGSSearchProvider(), breaker)
    for _ in range(5):
        assert service.search("nothing matches", 3) == []
    assert not breaker.is_open()
    fake_ddgs.error = None
    fake_ddgs.rows = [{"title": "T", "href": "https://e.com", "body": "b"}]
    assert [r.url for r in service.search("nothing matches", 3)] == ["https://e.com"]  # empty was not cached
