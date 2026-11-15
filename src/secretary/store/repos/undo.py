"""undo_entries repository (plan §8.4).

Class-B tools record the *inverse* of what they just did. ``apply`` replays it.
Only whitelisted tables and task fields can be touched, and an inverse is
refused when it would be unsafe (a reminder that already fired, an event that
already reached Google Calendar).
"""

from __future__ import annotations

import json
import sqlite3

from ._base import action_log, now_utc, row_to_dict

# Tables whose rows can be soft-deleted / restored by an undo.
_SOFT_TABLES = {"tasks", "notes", "events", "reminders"}
# Task columns an undo may set back.
_TASK_FIELDS = {"title", "notes", "priority", "due_at", "due_tz", "status", "completed_at"}


def record(con: sqlite3.Connection, turn_id: str | None, label: str, inverse: dict) -> int:
    cur = con.execute(
        "INSERT INTO undo_entries(turn_id, label, inverse_json, created_at) VALUES(?,?,?,?)",
        (turn_id, label, json.dumps(inverse), now_utc()),
    )
    return int(cur.lastrowid)


def get(con: sqlite3.Connection, entry_id: int) -> dict | None:
    cur = con.execute("SELECT * FROM undo_entries WHERE id=?", (entry_id,))
    row = cur.fetchone()
    return row_to_dict(cur, row) if row else None


def list_for_turn(con: sqlite3.Connection, turn_id: str) -> list[dict]:
    """Entries a turn created that have not been undone yet, oldest first."""
    cur = con.execute(
        "SELECT * FROM undo_entries WHERE turn_id=? AND undone_at IS NULL ORDER BY id",
        (turn_id,),
    )
    return [row_to_dict(cur, r) for r in cur.fetchall()]


def _changed(con: sqlite3.Connection) -> bool:
    return bool(con.execute("SELECT changes()").fetchone()[0])


def _soft_delete(con: sqlite3.Connection, table: str, row_id: int) -> tuple[bool, str]:
    guard = ""
    if table == "events":
        guard = " AND sync_state <> 'synced'"
    elif table == "reminders":
        guard = " AND status='scheduled'"
    now = now_utc()
    con.execute(
        f"UPDATE {table} SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL{guard}",
        (now, now, row_id),
    )
    if _changed(con):
        return True, "Undone."
    if table == "events":
        return False, "That event is already on Google Calendar; delete it there."
    if table == "reminders":
        return False, "That reminder already fired, so it can't be undone."
    return False, "Nothing to undo: it was already changed."


def _restore(con: sqlite3.Connection, table: str, row_id: int) -> tuple[bool, str]:
    guard = " AND status='scheduled'" if table == "reminders" else ""
    con.execute(
        f"UPDATE {table} SET deleted_at=NULL, updated_at=? WHERE id=? AND deleted_at IS NOT NULL{guard}",
        (now_utc(), row_id),
    )
    if _changed(con):
        return True, "Restored."
    return False, "Nothing to restore: it was already changed."


def _set_task_fields(con: sqlite3.Connection, row_id: int, fields: dict) -> tuple[bool, str]:
    safe = {k: v for k, v in fields.items() if k in _TASK_FIELDS}
    if not safe:
        return False, "Nothing to restore."
    sets = ", ".join(f"{k}=?" for k in safe)
    con.execute(
        f"UPDATE tasks SET {sets}, updated_at=? WHERE id=? AND deleted_at IS NULL",
        (*safe.values(), now_utc(), row_id),
    )
    if _changed(con):
        return True, "Restored the previous values."
    return False, "That task no longer exists."


def apply(con: sqlite3.Connection, entry_id: int) -> tuple[bool, str]:
    """Replay one entry's inverse. Returns (done, message for the user)."""
    entry = get(con, entry_id)
    if entry is None:
        return False, "Nothing to undo."
    if entry["undone_at"]:
        return False, "Already undone."
    try:
        inverse = json.loads(entry["inverse_json"])
    except json.JSONDecodeError:
        return False, "That undo entry is unreadable."
    op, table, row_id = inverse.get("op"), inverse.get("table"), inverse.get("id")
    if not isinstance(row_id, int):
        return False, "That undo entry is invalid."
    if op == "soft_delete" and table in _SOFT_TABLES:
        done, message = _soft_delete(con, table, row_id)
    elif op == "restore" and table in _SOFT_TABLES:
        done, message = _restore(con, table, row_id)
    elif op == "set" and table == "tasks":
        done, message = _set_task_fields(con, row_id, inverse.get("fields") or {})
    else:
        return False, "That undo entry is invalid."
    if done:
        con.execute("UPDATE undo_entries SET undone_at=? WHERE id=?", (now_utc(), entry_id))
        action_log(con, entry["turn_id"], "undone", table or "", row_id, {"label": entry["label"]})
    return done, message
