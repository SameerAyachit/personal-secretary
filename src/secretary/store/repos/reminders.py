"""reminders repository."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ._base import action_log, now_utc, row_to_dict


def create(
    con: sqlite3.Connection,
    *,
    task_id: int | None,
    title: str,
    body: str,
    kind: str,
    tz: str,
    rule_json: str | None,
    next_fire_at: str | None,
    priority: int = 0,
    idempotency_key: str | None = None,
    turn_id: str | None = None,
) -> int:
    now = now_utc()
    cur = con.execute(
        "INSERT INTO reminders(task_id, title, body, kind, tz, rule_json, next_fire_at, "
        "status, priority, idempotency_key, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (task_id, title, body, kind, tz, rule_json, next_fire_at, "scheduled", priority,
         idempotency_key, now, now),
    )
    rid = int(cur.lastrowid or 0)
    action_log(con, turn_id, "created", "reminder", rid, {"title": title, "kind": kind})
    return rid


def get(con: sqlite3.Connection, reminder_id: int) -> dict | None:
    cur = con.execute(
        "SELECT * FROM reminders WHERE id=? AND deleted_at IS NULL", (reminder_id,)
    )
    row = cur.fetchone()
    return row_to_dict(cur, row) if row else None


def list_all(
    con: sqlite3.Connection, *, status: str | None = None
) -> list[dict]:
    """Return non-deleted reminders, newest first (optionally filtered by status)."""
    q = "SELECT * FROM reminders WHERE deleted_at IS NULL"
    params: list[Any] = []
    if status is not None:
        q += " AND status=?"
        params.append(status)
    q += " ORDER BY datetime(next_fire_at) ASC NULLS LAST, id DESC"
    cur = con.execute(q, params)
    return [row_to_dict(cur, r) for r in cur.fetchall()]


def update(
    con: sqlite3.Connection,
    reminder_id: int,
    *,
    turn_id: str | None = None,
    **fields: Any,
) -> bool:
    allowed = {"title", "body", "kind", "tz", "rule_json", "next_fire_at", "status", "priority", "idempotency_key"}
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
    params.append(reminder_id)
    cur = con.execute(
        f"UPDATE reminders SET {', '.join(sets)} WHERE id=? AND deleted_at IS NULL", params
    )
    if cur.rowcount == 0:
        return False
    action_log(con, turn_id, "updated", "reminder", reminder_id, {"fields": list(fields)})
    return True


def soft_delete(con: sqlite3.Connection, reminder_id: int, turn_id: str | None = None) -> bool:
    cur = con.execute(
        "UPDATE reminders SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
        (now_utc(), now_utc(), reminder_id),
    )
    if cur.rowcount == 0:
        return False
    action_log(con, turn_id, "deleted", "reminder", reminder_id, None)
    return True


def rule(con: sqlite3.Connection, reminder_id: int) -> dict | None:
    cur = con.execute("SELECT rule_json FROM reminders WHERE id=?", (reminder_id,))
    row = cur.fetchone()
    if not row or row[0] is None:
        return None
    rule_data: dict | None = json.loads(row[0])
    return rule_data


def get_by_idempotency_key(con: sqlite3.Connection, key: str) -> dict | None:
    """Return a reminder by idempotency key, regardless of status."""
    cur = con.execute(
        "SELECT * FROM reminders WHERE idempotency_key=? AND deleted_at IS NULL",
        (key,),
    )
    row = cur.fetchone()
    return row_to_dict(cur, row) if row else None


# --- firing (used by the scheduler tick and startup catch-up) ---------------


def list_due(con: sqlite3.Connection, now_iso: str) -> list[dict]:
    """Scheduled, non-cancelled reminders whose fire time has passed, oldest first."""
    cur = con.execute(
        "SELECT * FROM reminders WHERE deleted_at IS NULL AND status='scheduled' "
        "AND next_fire_at IS NOT NULL AND next_fire_at <= ? ORDER BY next_fire_at",
        (now_iso,),
    )
    return [row_to_dict(cur, r) for r in cur.fetchall()]


def claim(con: sqlite3.Connection, reminder_id: int) -> bool:
    """Transition scheduled -> firing exactly once; False if someone else got it."""
    cur = con.execute(
        "UPDATE reminders SET status='firing' WHERE id=? AND status='scheduled'",
        (reminder_id,),
    )
    return cur.rowcount == 1


def release_claim(con: sqlite3.Connection, reminder_id: int) -> None:
    con.execute(
        "UPDATE reminders SET status='scheduled' WHERE id=? AND status='firing'",
        (reminder_id,),
    )


def record_run(
    con: sqlite3.Connection, reminder_id: int, scheduled_for: str, fired_at: str
) -> None:
    """Record a fired run; UNIQUE(reminder_id, scheduled_for) guards double fires."""
    con.execute(
        "INSERT INTO reminder_runs(reminder_id, scheduled_for, fired_at, outcome) "
        "VALUES(?,?,?,'fired')",
        (reminder_id, scheduled_for, fired_at),
    )


def reschedule(
    con: sqlite3.Connection, reminder_id: int, next_fire_at: str, now_iso: str
) -> None:
    con.execute(
        "UPDATE reminders SET next_fire_at=?, status='scheduled', updated_at=? WHERE id=?",
        (next_fire_at, now_iso, reminder_id),
    )


def mark_done(con: sqlite3.Connection, reminder_id: int, now_iso: str) -> None:
    con.execute(
        "UPDATE reminders SET status='done', updated_at=? WHERE id=?",
        (now_iso, reminder_id),
    )
