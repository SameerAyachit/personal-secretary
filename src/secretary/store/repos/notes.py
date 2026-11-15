"""notes repository (free-form notes the user dictates in chat)."""

from __future__ import annotations

import sqlite3

from ._base import action_log, now_utc, row_to_dict


def create(con: sqlite3.Connection, *, text: str, turn_id: str | None = None) -> int:
    now = now_utc()
    cur = con.execute(
        "INSERT INTO notes(text, created_at, updated_at) VALUES(?,?,?)", (text, now, now)
    )
    note_id = int(cur.lastrowid)
    action_log(con, turn_id, "created", "note", note_id, {"chars": len(text)})
    return note_id


def get(con: sqlite3.Connection, note_id: int) -> dict | None:
    cur = con.execute("SELECT * FROM notes WHERE id=? AND deleted_at IS NULL", (note_id,))
    row = cur.fetchone()
    return row_to_dict(cur, row) if row else None


def list_recent(con: sqlite3.Connection, *, limit: int = 100) -> list[dict]:
    cur = con.execute(
        "SELECT * FROM notes WHERE deleted_at IS NULL ORDER BY created_at DESC, id DESC LIMIT ?",
        (limit,),
    )
    return [row_to_dict(cur, r) for r in cur.fetchall()]


def search(con: sqlite3.Connection, query: str, *, limit: int = 20) -> list[dict]:
    """Case-insensitive substring match; LIKE wildcards in ``query`` are literal."""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    cur = con.execute(
        "SELECT * FROM notes WHERE deleted_at IS NULL AND text LIKE ? ESCAPE '\\' "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        (f"%{escaped}%", limit),
    )
    return [row_to_dict(cur, r) for r in cur.fetchall()]
