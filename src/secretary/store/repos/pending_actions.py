"""pending_actions repository (plan §8: class C gating)."""

from __future__ import annotations

import sqlite3

from ._base import action_log, now_utc, row_to_dict


def create(
    con: sqlite3.Connection,
    *,
    kind: str,
    summary: str,
    payload_json: str,
    expires_at: str,
    turn_id: str | None = None,
) -> int:
    now = now_utc()
    cur = con.execute(
        "INSERT INTO pending_actions(kind, summary, payload_json, status, created_at, expires_at) "
        "VALUES(?,?,?,'waiting',?,?)",
        (kind, summary, payload_json, now, expires_at),
    )
    pid = int(cur.lastrowid or 0)
    action_log(con, turn_id, "created", "pending_action", pid, {"kind": kind})
    return pid


def get(con: sqlite3.Connection, pending_id: int) -> dict | None:
    cur = con.execute("SELECT * FROM pending_actions WHERE id=?", (pending_id,))
    row = cur.fetchone()
    return row_to_dict(cur, row) if row else None


def list_waiting(con: sqlite3.Connection, *, now_iso: str) -> list[dict]:
    cur = con.execute(
        "SELECT * FROM pending_actions WHERE status='waiting' AND expires_at > ? "
        "ORDER BY created_at",
        (now_iso,),
    )
    return [row_to_dict(cur, r) for r in cur.fetchall()]


def decide(
    con: sqlite3.Connection,
    pending_id: int,
    status: str,
    *,
    turn_id: str | None = None,
    result_json: str | None = None,
) -> bool:
    allowed = {"approved", "rejected", "expired", "executed", "failed"}
    if status not in allowed:
        return False
    con.execute(
        "UPDATE pending_actions SET status=?, decided_at=?, result_json=? WHERE id=? AND status='waiting'",
        (status, now_utc(), result_json, pending_id),
    )
    # rowcount checked via separate get is simpler; rely on rowcount.
    cur = con.execute("SELECT changes() AS c")
    changed = cur.fetchone()[0]
    if not changed:
        return False
    action_log(con, turn_id, status, "pending_action", pending_id, {"result": result_json})
    return True


def finish(
    con: sqlite3.Connection,
    pending_id: int,
    status: str,
    *,
    turn_id: str | None = None,
    result_json: str | None = None,
) -> bool:
    """Record the outcome of an approved action (approved -> executed/failed)."""
    if status not in {"executed", "failed"}:
        return False
    con.execute(
        "UPDATE pending_actions SET status=?, result_json=? WHERE id=? AND status='approved'",
        (status, result_json, pending_id),
    )
    changed = con.execute("SELECT changes() AS c").fetchone()[0]
    if not changed:
        return False
    action_log(con, turn_id, status, "pending_action", pending_id, {"result": result_json})
    return True


def expire_waiting(con: sqlite3.Connection, now_iso: str) -> int:
    """Expire waiting actions whose ``expires_at`` has passed; returns the count."""
    cur = con.execute(
        "UPDATE pending_actions SET status='expired', decided_at=? "
        "WHERE status='waiting' AND expires_at < ?",
        (now_iso, now_iso),
    )
    return cur.rowcount


def purge_expired(con: sqlite3.Connection, older_than_iso: str) -> int:
    """Delete actions that expired (never decided by the user) before ``older_than_iso``."""
    cur = con.execute(
        "DELETE FROM pending_actions WHERE status='expired' AND decided_at < ?",
        (older_than_iso,),
    )
    return cur.rowcount
