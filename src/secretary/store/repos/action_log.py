"""action_log repository."""

from __future__ import annotations

import sqlite3

from ._base import row_to_dict


def list_for_entity(con: sqlite3.Connection, entity: str, entity_id: int, *, limit: int = 50) -> list[dict]:
    cur = con.execute(
        "SELECT * FROM action_log WHERE entity=? AND entity_id=? ORDER BY id DESC LIMIT ?",
        (entity, entity_id, limit),
    )
    return [row_to_dict(cur, r) for r in cur.fetchall()]


def recent(con: sqlite3.Connection, *, limit: int = 100) -> list[dict]:
    cur = con.execute("SELECT * FROM action_log ORDER BY id DESC LIMIT ?", (limit,))
    return [row_to_dict(cur, r) for r in cur.fetchall()]
