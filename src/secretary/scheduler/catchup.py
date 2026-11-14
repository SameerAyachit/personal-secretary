"""Catch-up logic: reconcile reminders missed while the app/PC was off (plan §10.4).

On startup/wake, reminders whose next_fire_at has passed are grouped into a
single "While you were away" inbox entry (never 20 toasts). Recurring reminders
are advanced to their next future occurrence; those older than 24 h are logged
as missed and skipped.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from secretary.scheduler.firing import advance, is_recurring, utc_iso
from secretary.store.db import Connection
from secretary.store.repos import inbox as inbox_repo
from secretary.store.repos import pending_actions as pa_repo
from secretary.store.repos import reminders as reminders_repo

MISSED_HOURS = 24


def now_utc() -> datetime:
    return datetime.now(UTC)


def catch_up(conn: Connection, tz_name: str = "Asia/Kolkata") -> dict:
    """Reconcile reminders missed while the app/PC was off.

    Returns a dict with the number of reminders folded into the catch-up
    inbox entry, for the caller to surface as one toast.
    """
    now = now_utc()
    now_iso = utc_iso(now)
    due = reminders_repo.list_due(conn, now_iso)
    if not due:
        return {"count": 0, "titles": []}

    titles: list[str] = []
    for rem in due:
        if not reminders_repo.claim(conn, rem["id"]):
            continue
        reminders_repo.record_run(conn, rem["id"], rem["next_fire_at"], now_iso)
        missed_dt = datetime.fromisoformat(rem["next_fire_at"].replace("Z", "+00:00"))
        stale_series = is_recurring(rem) and now - missed_dt > timedelta(hours=MISSED_HOURS)
        if not stale_series:  # recurring misses older than 24 h are skipped silently
            titles.append(rem["title"])
        advance(conn, rem, now)

    # One "While you were away" entry for the whole group.
    if titles:
        body = f"{len(titles)} reminder(s) while you were away:\n" + "\n".join(
            f"- {t}" for t in titles
        )
        inbox_repo.create(
            conn,
            kind="while_away",
            title="While you were away",
            body=body,
        )

    # Sweeper: expire pending actions.
    pa_repo.expire_waiting(conn, now_iso)
    return {"count": len(titles), "titles": titles}
