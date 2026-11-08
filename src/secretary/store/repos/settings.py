"""settings repository (key/value store)."""

from __future__ import annotations

import sqlite3

from ._base import action_log


def get(con: sqlite3.Connection, key: str) -> str | None:
    cur = con.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    return row[0] if row else None


def set(con: sqlite3.Connection, key: str, value: str, turn_id: str | None = None) -> None:
    con.execute(
        "INSERT INTO settings(key, value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    action_log(con, turn_id, "updated", "setting", None, {"key": key})
