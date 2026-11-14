"""events repository (calendar)."""

from __future__ import annotations

import sqlite3
from typing import Any

from ._base import action_log, now_utc, row_to_dict


def create(
    con: sqlite3.Connection,
    *,
    title: str,
    start_at: str,
    end_at: str | None,
    tz: str,
    all_day: int = 0,
    location: str | None = None,
    notes: str | None = None,
    google_event_id: str | None = None,
    etag: str | None = None,
    sync_state: str = "synced",
    turn_id: str | None = None,
) -> int:
    now = now_utc()
    cur = con.execute(
        "INSERT INTO events(title, start_at, end_at, tz, all_day, location, notes, google_event_id, etag, "
        "sync_state, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (title, start_at, end_at, tz, all_day, location, notes, google_event_id, etag, sync_state, now, now),
    )
    eid = int(cur.lastrowid)
    action_log(con, turn_id, "created", "event", eid, {"title": title})
    return eid


def list_window(con: sqlite3.Connection, *, start_at: str, end_at: str) -> list[dict]:
    cur = con.execute(
        "SELECT * FROM events WHERE deleted_at IS NULL AND start_at >= ? AND start_at < ? ORDER BY start_at",
        (start_at, end_at),
    )
    return [row_to_dict(cur, r) for r in cur.fetchall()]


def update(
    con: sqlite3.Connection,
    event_id: int,
    *,
    turn_id: str | None = None,
    **fields: Any,
) -> bool:
    allowed = {"title", "start_at", "end_at", "tz", "all_day", "location", "notes", "google_event_id", "etag"}
    sets = []
    params: list[Any] = []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            params.append(v)
    if not sets:
        return False
    sets.append("updated_at=?")
    params.append(now_utc())
    params.append(event_id)
    cur = con.execute(f"UPDATE events SET {', '.join(sets)} WHERE id=? AND deleted_at IS NULL", params)
    return cur.rowcount > 0


def list_pending(con: sqlite3.Connection, *, limit: int = 50) -> list[dict]:
    """Local events waiting to be pushed to Google Calendar."""
    cur = con.execute(
        "SELECT * FROM events WHERE deleted_at IS NULL AND sync_state='pending' ORDER BY id LIMIT ?",
        (limit,),
    )
    return [row_to_dict(cur, r) for r in cur.fetchall()]


def set_sync_state(
    con: sqlite3.Connection,
    event_id: int,
    state: str,
    *,
    etag: str | None = None,
    error: str | None = None,
) -> None:
    """Record the outcome of a push; ``etag`` is kept when not provided."""
    con.execute(
        "UPDATE events SET sync_state=?, sync_error=?, etag=COALESCE(?, etag), updated_at=? WHERE id=?",
        (state, error, etag, now_utc(), event_id),
    )


def get_by_google_id(con: sqlite3.Connection, google_event_id: str) -> dict | None:
    cur = con.execute("SELECT * FROM events WHERE google_event_id=?", (google_event_id,))
    row = cur.fetchone()
    return row_to_dict(cur, row) if row else None


def soft_delete_by_google_id(con: sqlite3.Connection, google_event_id: str) -> None:
    now = now_utc()
    con.execute(
        "UPDATE events SET deleted_at=?, updated_at=? WHERE google_event_id=? AND deleted_at IS NULL",
        (now, now, google_event_id),
    )
