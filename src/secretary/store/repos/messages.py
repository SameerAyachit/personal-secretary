"""messages repository (local email store for search/read/triage, plan §3.5)."""

from __future__ import annotations

import json
import logging
import sqlite3

from ._base import action_log, now_utc, row_to_dict

logger = logging.getLogger(__name__)

TRIAGE_CATEGORIES = ("personal", "work", "newsletter", "invoice", "spam")
TRIAGE_URGENCIES = ("low", "normal", "high")
TRIAGE_ACTIONS = ("reply", "archive", "read", "ignore")


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
    reply_to_id: int | None = None,
    turn_id: str | None = None,
) -> int:
    now = now_utc()
    cur = con.execute(
        "INSERT INTO email_messages(thread_id, from_addr, to_addrs, subject, body, received_at, "
        "is_read, source, google_message_id, reply_to_id, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (thread_id, from_addr, to_addrs, subject, body, received_at, is_read, source,
         google_message_id, reply_to_id, now, now),
    )
    mid = int(cur.lastrowid or 0)
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


def get_by_google_id(con: sqlite3.Connection, google_message_id: str) -> dict | None:
    """Return the locally stored message for a Gmail message id, if any."""
    cur = con.execute(
        "SELECT * FROM email_messages WHERE google_message_id=? AND deleted_at IS NULL",
        (google_message_id,),
    )
    row = cur.fetchone()
    return row_to_dict(cur, row) if row else None


def mark_read(con: sqlite3.Connection, message_id: int) -> bool:
    cur = con.execute(
        "UPDATE email_messages SET is_read=1, updated_at=? WHERE id=? AND is_read=0",
        (now_utc(), message_id),
    )
    return cur.rowcount > 0


def upsert_triage_result(
    con: sqlite3.Connection,
    message_id: int,
    category: str,
    urgency: str,
    suggested_action: str,
    turn_id: str | None = None,
) -> None:
    """Insert or replace the triage result for one message (enum-validated)."""
    if category not in TRIAGE_CATEGORIES:
        raise ValueError(f"unknown triage category: {category!r}")
    if urgency not in TRIAGE_URGENCIES:
        raise ValueError(f"unknown triage urgency: {urgency!r}")
    if suggested_action not in TRIAGE_ACTIONS:
        raise ValueError(f"unknown triage action: {suggested_action!r}")
    now = now_utc()
    con.execute(
        "INSERT INTO triage_results(message_id, category, urgency, suggested_action, created_at) "
        "VALUES(?,?,?,?,?) "
        "ON CONFLICT(message_id) DO UPDATE SET category=excluded.category, "
        "urgency=excluded.urgency, suggested_action=excluded.suggested_action, "
        "created_at=excluded.created_at",
        (message_id, category, urgency, suggested_action, now),
    )
    action_log(con, turn_id, "updated", "triage_result", message_id,
               {"category": category, "urgency": urgency, "suggested_action": suggested_action})


def list_triage_results(con: sqlite3.Connection, limit: int = 50) -> list[dict]:
    cur = con.execute(
        "SELECT m.id, m.from_addr, m.subject, m.received_at, t.category, t.urgency, "
        "t.suggested_action, t.created_at "
        "FROM triage_results t JOIN email_messages m ON m.id = t.message_id "
        "WHERE m.deleted_at IS NULL "
        "ORDER BY m.received_at DESC LIMIT ?",
        (limit,),
    )
    return [row_to_dict(cur, r) for r in cur.fetchall()]


def list_drafts(con: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """Unsent drafts, newest first."""
    cur = con.execute(
        "SELECT * FROM email_messages WHERE source='draft' AND deleted_at IS NULL "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        (limit,),
    )
    return [row_to_dict(cur, r) for r in cur.fetchall()]


def discard_draft(con: sqlite3.Connection, message_id: int, turn_id: str | None = None) -> bool:
    """Soft-delete a draft (never touches received mail)."""
    now = now_utc()
    con.execute(
        "UPDATE email_messages SET deleted_at=?, updated_at=? "
        "WHERE id=? AND source='draft' AND deleted_at IS NULL",
        (now, now, message_id),
    )
    if not con.execute("SELECT changes()").fetchone()[0]:
        return False
    action_log(con, turn_id, "deleted", "message", message_id, {"draft": True})
    return True


def mark_sent(con: sqlite3.Connection, message_id: int, turn_id: str | None = None) -> bool:
    """A draft that was sent through Gmail becomes a sent message."""
    con.execute(
        "UPDATE email_messages SET source='sent', updated_at=? WHERE id=? AND source='draft'",
        (now_utc(), message_id),
    )
    if not con.execute("SELECT changes()").fetchone()[0]:
        return False
    action_log(con, turn_id, "sent", "message", message_id, {})
    return True


def list_known_addresses(con: sqlite3.Connection) -> list[str]:
    """Addresses the user has already sent to or received from (message history)."""
    cur = con.execute(
        "SELECT from_addr, to_addrs FROM email_messages WHERE deleted_at IS NULL AND source <> 'draft'"
    )
    addresses: set[str] = set()
    for from_addr, to_addrs in cur.fetchall():
        addresses.add(from_addr)
        try:
            for addr in json.loads(to_addrs or "[]"):
                if isinstance(addr, str) and addr:
                    addresses.add(addr)
        except (json.JSONDecodeError, TypeError):
            continue
    return sorted(addresses)
