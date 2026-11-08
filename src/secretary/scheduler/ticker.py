"""Scheduler ticker: fires due reminders and runs the per-tick jobs (plan §10).

Runs on its own thread. Every tick (30 s):
  1. fire due reminders (atomic, one transaction per reminder),
  2. inbox repeat alerts,
  3. snooze expiry,
  4. sweeper (expire pending_actions).

Notification (toast/popup) happens **after** the DB commit so a crash between
commit and toast still leaves an unacknowledged inbox row that the UI shows on
next start — nothing is lost (plan §10.2).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from PySide6.QtCore import QThread

from secretary.store.db import Connection
from secretary.store.repos import inbox as inbox_repo
from secretary.timeparse.recurrence import RecurrenceRule, next_occurrence

TICK_SECONDS = 30
REPEAT_ALERT_MINUTES = 10


def now_utc() -> datetime:
    return datetime.now(UTC)


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fire_due(conn: sqlite3.Connection) -> list[dict]:
    """Fire all due reminders atomically. Returns the created inbox rows."""
    now_iso = _utc_iso(now_utc())
    due = conn.execute(
        "SELECT * FROM reminders WHERE status='scheduled' AND next_fire_at IS NOT NULL "
        "AND next_fire_at <= ? ORDER BY next_fire_at",
        (now_iso,),
    ).fetchall()
    created: list[dict] = []
    for raw in due:
        rem = raw
        # Claim: transition scheduled -> firing, exactly once.
        cur = conn.execute(
            "UPDATE reminders SET status='firing' WHERE id=? AND status='scheduled'",
            (rem["id"],),
        )
        if cur.rowcount == 0:
            continue  # already claimed by another tick/process
        try:
            # Record the run.
            conn.execute(
                "INSERT INTO reminder_runs(reminder_id, scheduled_for, fired_at, outcome) "
                "VALUES(?,?,?,'fired')",
                (rem["id"], rem["next_fire_at"], now_iso),
            )
            # Inbox row (source of truth; written before the toast).
            inbox_id = inbox_repo.create(
                conn,
                kind="reminder",
                reminder_id=rem["id"],
                title=rem["title"],
                body=rem["body"],
                turn_id=None,
            )
            # Advance the series or mark done.
            if rem["kind"] == "recurring" and rem["rule_json"]:
                rule = RecurrenceRule(**json.loads(rem["rule_json"]))
                tz = ZoneInfo(rem["tz"])
                after_local = now_utc().astimezone(tz)
                nxt = next_occurrence(rule, after_local, rem["tz"])
                conn.execute(
                    "UPDATE reminders SET next_fire_at=?, status='scheduled', updated_at=? WHERE id=?",
                    (_utc_iso(nxt), now_iso, rem["id"]),
                )
            else:
                conn.execute(
                    "UPDATE reminders SET status='done', updated_at=? WHERE id=?",
                    (now_iso, rem["id"]),
                )
            created.append(
                {"inbox_id": inbox_id, "reminder_id": rem["id"], "title": rem["title"], "body": rem["body"]}
            )
        except sqlite3.IntegrityError:
            # A run already exists for this (reminder, scheduled_for) — skip duplicate.
            continue
    return created


def _repeat_alerts(conn: sqlite3.Connection) -> None:
    """Unacknowledged for >= 10 minutes and repeat_sent=0 -> one repeat toast."""
    cutoff = _utc_iso(now_utc() - timedelta(minutes=REPEAT_ALERT_MINUTES))
    conn.execute(
        "UPDATE inbox SET repeat_sent=1 "
        "WHERE kind='reminder' AND status='unacknowledged' AND repeat_sent=0 AND created_at <= ?",
        (cutoff,),
    )


def _snooze_expiry(conn: sqlite3.Connection) -> None:
    """Snoozed items whose snoozed_until <= now -> back to unacknowledged."""
    now_iso = _utc_iso(now_utc())
    conn.execute(
        "UPDATE inbox SET status='unacknowledged', snoozed_until=NULL "
        "WHERE status='snoozed' AND snoozed_until IS NOT NULL AND snoozed_until <= ?",
        (now_iso,),
    )


def _sweeper(conn: sqlite3.Connection) -> None:
    """Expire pending_actions whose expires_at < now."""
    now_iso = _utc_iso(now_utc())
    conn.execute(
        "UPDATE pending_actions SET status='expired', decided_at=? "
        "WHERE status='waiting' AND expires_at < ?",
        (now_iso, now_iso),
    )


def tick(conn: Connection, on_fired=None) -> None:
    """Run one tick: fire due reminders, repeat alerts, snooze expiry, sweeper."""
    try:
        due = conn.write(_fire_due)
    except Exception as exc:
        due = []
        print(f"scheduler fire failed: {exc}")
    if due and on_fired is not None:
        try:
            on_fired(due)
        except Exception as exc:
            print(f"scheduler notify failed: {exc}")
    for step in (_repeat_alerts, _snooze_expiry, _sweeper):
        try:
            conn.write(step)
        except Exception as exc:
            print(f"scheduler step {step.__name__} failed: {exc}")


class SchedulerThread(QThread):
    """Owns the scheduler tick loop on its own thread (plan §10.1)."""

    def __init__(self, conn: Connection, on_fired=None) -> None:
        super().__init__()
        self._conn = conn
        self._on_fired = on_fired
        self._running = True

    def run(self) -> None:  # type: ignore[override]
        while self._running:
            tick(self._conn, self._on_fired)
            self.msleep(TICK_SECONDS * 1000)

    def stop(self) -> None:
        self._running = False
