"""conversations and messages repository."""

from __future__ import annotations

import sqlite3

from ._base import now_utc, row_to_dict


def create_conversation(con: sqlite3.Connection, *, title: str | None = None, turn_id: str | None = None) -> int:
    now = now_utc()
    cur = con.execute(
        "INSERT INTO conversations(title, created_at, summary) VALUES(?,?,?)",
        (title, now, ""),
    )
    return int(cur.lastrowid)


def add_message(
    con: sqlite3.Connection,
    *,
    conversation_id: int,
    role: str,
    content: str,
    tool_name: str | None = None,
    tool_calls_json: str | None = None,
    turn_id: str | None = None,
    tokens: int | None = None,
) -> int:
    now = now_utc()
    cur = con.execute(
        "INSERT INTO messages(conversation_id, role, content, tool_name, tool_calls_json, turn_id, tokens, created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (conversation_id, role, content, tool_name, tool_calls_json, turn_id, tokens, now),
    )
    return int(cur.lastrowid)


def list_messages(con: sqlite3.Connection, conversation_id: int, *, limit: int = 50) -> list[dict]:
    cur = con.execute(
        "SELECT * FROM messages WHERE conversation_id=? ORDER BY id LIMIT ?",
        (conversation_id, limit),
    )
    return [row_to_dict(cur, r) for r in cur.fetchall()]
