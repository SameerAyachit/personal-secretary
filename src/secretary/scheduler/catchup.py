"""Catch-up logic: reconcile reminders missed while the app/PC was off (plan §10.4).

On startup/wake, reminders whose next_fire_at has passed are grouped into a
single "While you were away" inbox entry (never 20 toasts). Recurring reminders
are advanced to their next future occurrence; those older than 24 h are logged
as missed and skipped.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from secretary.store.db import Connection
from secretary.store.repos import inbox as inbox_repo
from secretary.store.repos import pending_actions as pa_repo
from secretary.timeparse.recurrence import RecurrenceRule, next_occurrence

MISSED_HOURS = 24


def now_utc() -> datetime:
    return datetime.now(UTC)


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def catch_up(conn: Connection, tz_name: str = "Asia/Kolkata") -> dict:
    """Reconcile reminders missed while the app/PC was off.

    Returns a dict with the number of reminders folded into the catch-up
    inbox entry, for the caller to surface as one toast.
    """
    now = now_utc()
    now_iso = _utc_iso(now)
    due = conn.execute(
        "SELECT * FROM reminders WHERE status='scheduled' AND next_fire_at IS NOT NULL "
        "AND next_fire_at <= ? ORDER BY next_fire_at",
        (now_iso,),
    ).fetchall()
    if not due:
        return {"count": 0, "titles": []}

    titles: list[str] = []
    for raw in due:
        rem = dict(raw)
        # Claim: transition scheduled -> firing, exactly once.
        cur = conn.execute(
            "UPDATE reminders SET status='firing' WHERE id=? AND status='scheduled'",
            (rem["id"],),
        )
        if cur.rowcount == 0:
            continue
        # Record the run.
        conn.execute(
            "INSERT INTO reminder_runs(reminder_id, scheduled_for, fired_at, outcome) "
            "VALUES(?,?,?,'fired')",
            (rem["id"], rem["next_fire_at"], now_iso),
        )
        if rem["kind"] == "recurring" and rem["rule_json"]:
            rule = RecurrenceRule(**json.loads(rem["rule_json"]))
            tz = ZoneInfo(rem["tz"])
            after_local = now.astimezone(tz)
            missed_dt = datetime.fromisoformat(rem["next_fire_at"].replace("Z", "+00:00"))
            if now - missed_dt > timedelta(hours=MISSED_HOURS):
                # Older than 24 h: log as missed, advance the series, skip.
                nxt = next_occurrence(rule, after_local, rem["tz"])
                conn.execute(
                    "UPDATE reminders SET next_fire_at=?, status='scheduled', updated_at=? WHERE id=?",
                    (_utc_iso(nxt), now_iso, rem["id"]),
                )
                continue
            titles.append(rem["title"])
            nxt = next_occurrence(rule, after_local, rem["tz"])
            conn.execute(
                "UPDATE reminders SET next_fire_at=?, status='scheduled', updated_at=? WHERE id=?",
                (_utc_iso(nxt), now_iso, rem["id"]),
            )
        else:
            titles.append(rem["title"])
            conn.execute(
                "UPDATE reminders SET status='done', updated_at=? WHERE id=?",
                (now_iso, rem["id"]),
            )

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
