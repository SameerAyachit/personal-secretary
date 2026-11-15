"""research_briefs repository: background research jobs and their results (plan §14.3)."""

from __future__ import annotations

import json
import sqlite3

from ._base import now_utc, row_to_dict


def create(con: sqlite3.Connection, topic: str) -> int:
    cur = con.execute(
        "INSERT INTO research_briefs(topic, status, created_at) VALUES(?, 'running', ?)",
        (topic, now_utc()),
    )
    return int(cur.lastrowid or 0)


def finish(
    con: sqlite3.Connection, brief_id: int, brief: str, sources: list[dict], partial: bool
) -> None:
    con.execute(
        "UPDATE research_briefs SET status='done', brief=?, sources_json=?, partial=?, finished_at=? WHERE id=?",
        (brief, json.dumps(sources), 1 if partial else 0, now_utc(), brief_id),
    )


def fail(con: sqlite3.Connection, brief_id: int, error: str) -> None:
    con.execute(
        "UPDATE research_briefs SET status='failed', error=?, finished_at=? WHERE id=?",
        (error, now_utc(), brief_id),
    )


def get(con: sqlite3.Connection, brief_id: int) -> dict | None:
    cur = con.execute("SELECT * FROM research_briefs WHERE id=?", (brief_id,))
    row = cur.fetchone()
    return row_to_dict(cur, row) if row else None


def list_recent(con: sqlite3.Connection, limit: int = 20) -> list[dict]:
    cur = con.execute("SELECT * FROM research_briefs ORDER BY id DESC LIMIT ?", (limit,))
    return [row_to_dict(cur, r) for r in cur.fetchall()]


def fail_stale_running(con: sqlite3.Connection) -> int:
    """At startup: jobs left 'running' by a closed app can never finish; mark them failed."""
    cur = con.execute(
        "UPDATE research_briefs SET status='failed', error='Interrupted: the app was closed.', finished_at=? "
        "WHERE status='running'",
        (now_utc(),),
    )
    return cur.rowcount
