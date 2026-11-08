"""inbox repository (plan §10: inbox-first reminders)."""

from __future__ import annotations

import sqlite3
from typing import Any

from ._base import action_log, now_utc, row_to_dict


def create(
    con: sqlite3.Connection,
    *,
    kind: str,
    title: str,
    body: str,
    reminder_id: int | None = None,
    payload_json: str | None = None,
    turn_id: str | None = None,
) -> int:
    now = now_utc()
    cur = con.execute(
        "INSERT INTO inbox(kind, reminder_id, title, body, payload_json, status, created_at) "
        "VALUES(?,?,?,?,?,'unacknowledged',?)",
        (kind, reminder_id, title, body, payload_json, now),
    )
    iid = int(cur.lastrowid)
    action_log(con, turn_id, "created", "inbox", iid, {"kind": kind})
    return iid


def get(con: sqlite3.Connection, inbox_id: int) -> dict | None:
    cur = con.execute("SELECT * FROM inbox WHERE id=?", (inbox_id,))
    row = cur.fetchone()
    return row_to_dict(cur, row) if row else None


def list_unacknowledged(con: sqlite3.Connection, *, limit: int = 200) -> list[dict]:
    cur = con.execute(
        "SELECT * FROM inbox WHERE status='unacknowledged' ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return [row_to_dict(cur, r) for r in cur.fetchall()]


def update(
    con: sqlite3.Connection,
    inbox_id: int,
    *,
    turn_id: str | None = None,
    **fields: Any,
) -> bool:
    allowed = {"title", "body", "status", "snoozed_until", "acknowledged_at", "last_notified_at", "repeat_sent", "payload_json"}
    sets = []
    params: list[Any] = []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            params.append(v)
    if not sets:
        return False
    cur = con.execute(f"UPDATE inbox SET {', '.join(sets)} WHERE id=?", params)
    if cur.rowcount == 0:
        return False
    action_log(con, turn_id, "updated", "inbox", inbox_id, {"fields": list(fields)})
    return True
