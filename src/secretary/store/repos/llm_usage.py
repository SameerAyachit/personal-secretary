"""llm_usage and search_cache repositories."""

from __future__ import annotations

import sqlite3

from ._base import now_utc, row_to_dict


def record_usage(
    con: sqlite3.Connection,
    *,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    ok: bool,
    error: str | None = None,
    purpose: str = "chat",
) -> None:
    con.execute(
        "INSERT INTO llm_usage(ts, provider, model, prompt_tokens, completion_tokens, latency_ms, ok, error, purpose) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (now_utc(), provider, model, prompt_tokens, completion_tokens, latency_ms, 1 if ok else 0, error, purpose),
    )


def list_usage(con: sqlite3.Connection, *, limit: int = 200) -> list[dict]:
    cur = con.execute("SELECT * FROM llm_usage ORDER BY ts DESC LIMIT ?", (limit,))
    return [row_to_dict(cur, r) for r in cur.fetchall()]


def search_cache_get(con: sqlite3.Connection, query_hash: str) -> dict | None:
    cur = con.execute("SELECT * FROM search_cache WHERE query_hash=?", (query_hash,))
    row = cur.fetchone()
    return dict(row) if row else None


def search_cache_set(
    con: sqlite3.Connection,
    *,
    query_hash: str,
    query: str,
    results_json: str,
    fetched_at: str,
) -> None:
    con.execute(
        "INSERT INTO search_cache(query_hash, query, results_json, fetched_at) "
        "VALUES(?,?,?,?) "
        "ON CONFLICT(query_hash) DO UPDATE SET query=excluded.query, results_json=excluded.results_json, fetched_at=excluded.fetched_at",
        (query_hash, query, results_json, fetched_at),
    )
