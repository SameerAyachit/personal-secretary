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
    series_id: str | None = None,
    recurrence_json: str | None = None,
) -> int:
    now = now_utc()
    cur = con.execute(
        "INSERT INTO events(title, start_at, end_at, tz, all_day, location, notes, google_event_id, etag, "
        "sync_state, series_id, recurrence_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (title, start_at, end_at, tz, all_day, location, notes, google_event_id, etag, sync_state,
         series_id, recurrence_json, now, now),
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


def get(con: sqlite3.Connection, event_id: int) -> dict | None:
    cur = con.execute("SELECT * FROM events WHERE id=? AND deleted_at IS NULL", (event_id,))
    row = cur.fetchone()
    return row_to_dict(cur, row) if row else None


def list_from(con: sqlite3.Connection, *, since: str, limit: int = 200) -> list[dict]:
    """Non-deleted events starting at or after ``since`` (ISO), soonest first."""
    cur = con.execute(
        "SELECT * FROM events WHERE deleted_at IS NULL AND start_at >= ? ORDER BY start_at LIMIT ?",
        (since, limit),
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
    if cur.rowcount > 0:
        action_log(con, turn_id, "updated", "event", event_id, {"fields": list(fields)})
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


def series_overview(con: sqlite3.Connection) -> list[dict]:
    """One entry per recurring series that still has a live occurrence.

    ``last_start`` is the latest start over *all* rows (deleted ones included, so a
    removed last occurrence is never regenerated); ``template`` is the latest live row.
    """
    cur = con.execute(
        "SELECT series_id, MAX(start_at) AS last_start FROM events WHERE series_id IS NOT NULL "
        "GROUP BY series_id HAVING SUM(deleted_at IS NULL) > 0"
    )
    heads = [(r[0], r[1]) for r in cur.fetchall()]
    out: list[dict] = []
    for series_id, last_start in heads:
        cur = con.execute(
            "SELECT * FROM events WHERE series_id=? AND deleted_at IS NULL ORDER BY start_at DESC LIMIT 1",
            (series_id,),
        )
        row = cur.fetchone()
        if row is not None:
            out.append({"series_id": series_id, "last_start": last_start, "template": row_to_dict(cur, row)})
    return out


def soft_delete_series(con: sqlite3.Connection, series_id: str) -> tuple[int, int]:
    """Soft-delete the series' occurrences that are not on Google Calendar yet.

    Returns ``(deleted, kept)``; ``kept`` are occurrences already synced to Google.
    """
    now = now_utc()
    cur = con.execute(
        "UPDATE events SET deleted_at=?, updated_at=? WHERE series_id=? AND deleted_at IS NULL "
        "AND sync_state <> 'synced'",
        (now, now, series_id),
    )
    deleted = cur.rowcount
    kept = con.execute(
        "SELECT COUNT(*) FROM events WHERE series_id=? AND deleted_at IS NULL", (series_id,)
    ).fetchone()[0]
    return deleted, int(kept)
