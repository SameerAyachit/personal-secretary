"""messages repository (local email store for search/read/triage, plan §3.5)."""

from __future__ import annotations

import sqlite3

from ._base import action_log, now_utc, row_to_dict


def create(
    con: sqlite3.Connection,
    *,
    thread_id: str = "",
    from_addr: str,
    to_addrs: str = "[]",
    subject: str = "",
    body: str = "",
    received_at: str,
    is_read: int = 0,
    source: str = "local",
    google_message_id: str | None = None,
    turn_id: str | None = None,
) -> int:
    now = now_utc()
    cur = con.execute(
        "INSERT INTO email_messages(thread_id, from_addr, to_addrs, subject, body, received_at, "
        "is_read, source, google_message_id, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (thread_id, from_addr, to_addrs, subject, body, received_at, is_read, source,
         google_message_id, now, now),
    )
    mid = int(cur.lastrowid)
    action_log(con, turn_id, "created", "message", mid, {"subject": subject})
    return mid


def get(con: sqlite3.Connection, message_id: int) -> dict | None:
    cur = con.execute("SELECT * FROM email_messages WHERE id=? AND deleted_at IS NULL", (message_id,))
    row = cur.fetchone()
    return row_to_dict(cur, row) if row else None


def list_search(
    con: sqlite3.Connection, query: str, limit: int = 20
) -> list[dict]:
    like = f"%{query}%"
    cur = con.execute(
        "SELECT * FROM email_messages WHERE deleted_at IS NULL AND source <> 'draft' AND "
        "(subject LIKE ? OR body LIKE ? OR from_addr LIKE ?) "
        "ORDER BY received_at DESC LIMIT ?",
        (like, like, like, limit),
    )
    return [row_to_dict(cur, r) for r in cur.fetchall()]


def list_unread(con: sqlite3.Connection, limit: int = 50) -> list[dict]:
    cur = con.execute(
        "SELECT * FROM email_messages WHERE deleted_at IS NULL AND source <> 'draft' AND is_read=0 "
        "ORDER BY received_at DESC LIMIT ?",
        (limit,),
    )
    return [row_to_dict(cur, r) for r in cur.fetchall()]


def mark_read(con: sqlite3.Connection, message_id: int) -> bool:
    cur = con.execute(
        "UPDATE email_messages SET is_read=1, updated_at=? WHERE id=? AND is_read=0",
        (now_utc(), message_id),
    )
    return cur.rowcount > 0
