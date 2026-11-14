"""search_cache repository (web search results, keyed by query hash)."""

from __future__ import annotations

import sqlite3


def get(con: sqlite3.Connection, query_hash: str, newer_than_iso: str) -> str | None:
    """Cached ``results_json`` fetched after ``newer_than_iso``, else None."""
    row = con.execute(
        "SELECT results_json FROM search_cache WHERE query_hash=? AND fetched_at > ?",
        (query_hash, newer_than_iso),
    ).fetchone()
    return row[0] if row else None


def put(
    con: sqlite3.Connection, query_hash: str, query: str, results_json: str, fetched_at: str
) -> None:
    con.execute(
        "INSERT INTO search_cache(query_hash, query, results_json, fetched_at) "
        "VALUES(?,?,?,?) "
        "ON CONFLICT(query_hash) DO UPDATE SET query=excluded.query, "
        "results_json=excluded.results_json, fetched_at=excluded.fetched_at",
        (query_hash, query, results_json, fetched_at),
    )
