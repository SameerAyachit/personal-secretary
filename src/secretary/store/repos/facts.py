"""facts repository (user-approved long-term memory)."""

from __future__ import annotations

import sqlite3

from ._base import action_log, now_utc, row_to_dict


def upsert(con: sqlite3.Connection, key: str, value: str) -> None:
    now = now_utc()
    con.execute(
        "INSERT INTO facts(key, value, created_at, updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value, now, now),
    )


def get(con: sqlite3.Connection, key: str) -> str | None:
    cur = con.execute("SELECT value FROM facts WHERE key=?", (key,))
    row = cur.fetchone()
    return row[0] if row else None


def list_all(con: sqlite3.Connection) -> list[dict]:
    cur = con.execute("SELECT * FROM facts ORDER BY key")
    return [row_to_dict(cur, r) for r in cur.fetchall()]


def delete(con: sqlite3.Connection, key: str) -> bool:
    cur = con.execute("DELETE FROM facts WHERE key=?", (key,))
    if cur.rowcount == 0:
        return False
    action_log(con, None, "deleted", "fact", None, {"key": key})
    return True
