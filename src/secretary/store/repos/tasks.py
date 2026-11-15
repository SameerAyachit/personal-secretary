"""tasks repository."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ._base import action_log, now_utc, row_to_dict


def create(
    con: sqlite3.Connection,
    *,
    title: str,
    notes: str | None = None,
    due_at: str | None = None,
    due_tz: str | None = None,
    source: str = "user",
    turn_id: str | None = None,
) -> int:
    now = now_utc()
    cur = con.execute(
        "INSERT INTO tasks(title, notes, due_at, due_tz, source, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (title, notes, due_at, due_tz, source, now, now),
    )
    tid = int(cur.lastrowid)
    action_log(con, turn_id, "created", "task", tid, {"title": title})
    return tid


def get(con: sqlite3.Connection, task_id: int) -> dict | None:
    cur = con.execute(
        "SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (task_id,)
    )
    row = cur.fetchone()
    return row_to_dict(cur, row) if row else None


def list_open(
    con: sqlite3.Connection, *, limit: int = 100, offset: int = 0
) -> list[dict]:
    cur = con.execute(
        "SELECT * FROM tasks WHERE deleted_at IS NULL AND status='open' "
        "ORDER BY due_at IS NULL, due_at, id LIMIT ? OFFSET ?",
        (limit, offset),
    )
    return [row_to_dict(cur, r) for r in cur.fetchall()]


def list_all(con: sqlite3.Connection, *, status: str | None = None, limit: int = 500) -> list[dict]:
    """Non-deleted tasks, optionally of one status, soonest due first."""
    if status is None:
        cur = con.execute(
            "SELECT * FROM tasks WHERE deleted_at IS NULL ORDER BY due_at IS NULL, due_at, id LIMIT ?",
            (limit,),
        )
    else:
        cur = con.execute(
            "SELECT * FROM tasks WHERE deleted_at IS NULL AND status=? "
            "ORDER BY due_at IS NULL, due_at, id LIMIT ?",
            (status, limit),
        )
    return [row_to_dict(cur, r) for r in cur.fetchall()]


def update(
    con: sqlite3.Connection,
    task_id: int,
    *,
    turn_id: str | None = None,
    **fields: Any,
) -> bool:
    allowed = {"title", "notes", "status", "priority", "due_at", "due_tz", "source", "completed_at"}
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
    params.append(task_id)
    cur = con.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=? AND deleted_at IS NULL", params)
    if cur.rowcount == 0:
        return False
    action_log(con, turn_id, "updated", "task", task_id, {"fields": list(fields)})
    return True


def soft_delete(con: sqlite3.Connection, task_id: int, turn_id: str | None = None) -> bool:
    cur = con.execute(
        "UPDATE tasks SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
        (now_utc(), now_utc(), task_id),
    )
    if cur.rowcount == 0:
        return False
    action_log(con, turn_id, "deleted", "task", task_id, None)
    return True


def undo(con: sqlite3.Connection, detail_json: str | None) -> bool:
    """Undo a soft delete by restoring detail_json if present."""
    if not detail_json:
        return False

    detail = json.loads(detail_json)
    entity_id = detail.get("entity_id")
    if not entity_id:
        return False
    con.execute(
        "UPDATE tasks SET deleted_at=NULL, updated_at=? WHERE id=?",
        (now_utc(), entity_id),
    )
    return True
