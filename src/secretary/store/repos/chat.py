"""Chat transcript repository: conversations + messages."""

from __future__ import annotations

import sqlite3

from ._base import now_utc


def recent_messages(con: sqlite3.Connection, limit: int) -> list[dict]:
    """Latest user/assistant messages, oldest first (for the next turn's context)."""
    rows = con.execute(
        "SELECT role, content FROM messages WHERE role IN ('user','assistant') "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


def add_message(
    con: sqlite3.Connection, role: str, content: str, turn_id: str | None = None
) -> int:
    """Append a message to the latest conversation (creating one if none exists)."""
    now = now_utc()
    conv = con.execute("SELECT id FROM conversations ORDER BY id DESC LIMIT 1").fetchone()
    if conv is None:
        conv_id = int(
            con.execute(
                "INSERT INTO conversations(title, created_at) VALUES(?,?)", ("Chat", now)
            ).lastrowid
        )
    else:
        conv_id = conv[0]
    cur = con.execute(
        "INSERT INTO messages(conversation_id, role, content, turn_id, created_at) "
        "VALUES(?,?,?,?,?)",
        (conv_id, role, content, turn_id, now),
    )
    return int(cur.lastrowid)
