"""Read-only audit queries (used by scripts/check_utc_bug.py)."""

from __future__ import annotations

import sqlite3

from ._base import row_to_dict


def chat_items_before(con: sqlite3.Connection, before_iso: str) -> dict[str, list[dict]]:
    """Reminders and events that a chat turn created before ``before_iso`` and that are still ahead.

    Used to find items made before the absolute-time fix (clock times were read as UTC).
    """
    cur = con.execute(
        "SELECT r.id, r.title, r.next_fire_at AS at, r.tz, r.created_at FROM reminders r "
        "WHERE r.deleted_at IS NULL AND r.status='scheduled' AND r.created_at < ? "
        "AND EXISTS(SELECT 1 FROM action_log a WHERE a.entity='reminder' AND a.entity_id=r.id "
        "AND a.event='created' AND a.turn_id IS NOT NULL) ORDER BY r.next_fire_at",
        (before_iso,),
    )
    reminders = [row_to_dict(cur, r) for r in cur.fetchall()]
    cur = con.execute(
        "SELECT e.id, e.title, e.start_at AS at, e.tz, e.created_at FROM events e "
        "WHERE e.deleted_at IS NULL AND e.created_at < ? "
        "AND EXISTS(SELECT 1 FROM action_log a WHERE a.entity='event' AND a.entity_id=e.id "
        "AND a.event='created' AND a.turn_id IS NOT NULL) ORDER BY e.start_at",
        (before_iso,),
    )
    events = [row_to_dict(cur, r) for r in cur.fetchall()]
    return {"reminders": reminders, "events": events}
