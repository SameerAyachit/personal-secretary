"""Scheduler ticker: fires due reminders and runs the per-tick jobs (plan §10).

Runs on its own thread. Every tick (30 s):
  1. fire due reminders (atomic, one transaction per reminder),
  2. inbox repeat alerts,
  3. snooze expiry,
  4. sweeper (expire pending_actions),
  5. timezone change banner (when the system time zone changes).

Notification (toast/popup) happens **after** the DB commit so a crash between
commit and toast still leaves an unacknowledged inbox row that the UI shows on
next start — nothing is lost (plan §10.2).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from PySide6.QtCore import QThread

from secretary.scheduler.triage_job import run_triage_job
from secretary.store.db import Connection
from secretary.store.repos import inbox as inbox_repo
from secretary.store.repos import settings as settings_repo
from secretary.timeparse.recurrence import RecurrenceRule, next_occurrence

logger = logging.getLogger(__name__)

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
            # A run already exists for this (reminder, scheduled_for) — release
            # the 'firing' claim so the reminder is not stuck in 'firing'.
            conn.execute(
                "UPDATE reminders SET status='scheduled' WHERE id=? AND status='firing'",
                (rem["id"],),
            )
            continue
    return created


def _repeat_alerts(conn: sqlite3.Connection) -> list[dict]:
    """Unacknowledged for >= 10 minutes and repeat_sent=0 -> one repeat toast.

    Returns the items that need a repeat notification so the caller can toast
    them. Each is marked repeat_sent=1 so it only repeats once.
    """
    cutoff = _utc_iso(now_utc() - timedelta(minutes=REPEAT_ALERT_MINUTES))
    rows = conn.execute(
        "SELECT id, title, body FROM inbox WHERE kind='reminder' AND status='unacknowledged' "
        "AND repeat_sent=0 AND created_at <= ?",
        (cutoff,),
    ).fetchall()
    conn.execute(
        "UPDATE inbox SET repeat_sent=1 "
        "WHERE kind='reminder' AND status='unacknowledged' AND repeat_sent=0 AND created_at <= ?",
        (cutoff,),
    )
    return [{"id": r[0], "title": r[1], "body": r[2]} for r in rows]


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


def _tz_signature() -> str:
    """Signature of the current system time zone (offset + DST state + names)."""
    return f"{time.timezone}:{time.altzone}:{time.tzname[0]}:{time.tzname[1]}"


def _timezone_banner_step(conn: Connection, notifier) -> None:
    """Show one banner when the system time zone changes (plan C-23).

    Creates an inbox item and asks the notifier to toast once per change;
    the stored signature is updated so the banner does not repeat.
    """
    current = _tz_signature()
    stored = settings_repo.get(conn, "system_timezone")
    changed = stored is not None and stored != current

    def _persist(con: sqlite3.Connection) -> None:
        settings_repo.set(con, "system_timezone", current, turn_id="timezone-banner")
        if changed:
            inbox_repo.create(
                con,
                kind="system",
                title="Time zone changed",
                body="Your system time zone changed; reminder times now follow the new time zone.",
                turn_id="timezone-banner",
            )

    conn.write(_persist)
    if changed and notifier is not None:
        notifier.notify(
            "Time zone changed",
            "Your system time zone changed; reminder times now follow the new time zone.",
            priority=True,
        )


def tick(
    conn: Connection,
    on_fired=None,
    gmail_client=None,
    classify=None,
    notifier=None,
) -> None:
    """Run one tick: fire due reminders, repeat alerts, snooze expiry, sweeper,
    the Gmail triage job (plan §13.4), and the timezone change banner (C-23)."""
    logger.info("scheduler tick: started")
    try:
        due = conn.write(_fire_due)
    except Exception:
        due = []
        logger.exception("scheduler fire failed")
    if due and on_fired is not None:
        logger.info("scheduler tick: fired %d reminder(s)", len(due))
        try:
            on_fired(due)
        except Exception:
            logger.exception("scheduler notify failed")
    for step in (_snooze_expiry, _sweeper):
        try:
            conn.write(step)
        except Exception:
            logger.exception("scheduler step %s failed", step.__name__)
    # Repeat alerts: items unacknowledged >= 10 minutes get one repeat toast.
    try:
        repeats = conn.write(_repeat_alerts)
        for entry in repeats or []:
            if notifier is not None:
                notifier.notify(entry["title"], entry["body"], priority=True)
    except Exception:
        logger.exception("scheduler repeat alerts failed")
    # Gmail triage job (network + DB writes; every failure logged, never stops
    # the tick; no-op when neither dependency is configured).
    try:
        summary = run_triage_job(conn, gmail_client=gmail_client, classify=classify)
        if summary["synced"] or summary["triaged"]:
            logger.info(
                "scheduler triage job: synced=%d triaged=%d",
                summary["synced"],
                summary["triaged"],
            )
    except Exception:
        logger.exception("scheduler triage job failed")
    # Timezone change banner (plan C-23): when the system time zone changes,
    # show an inbox item + toast. Runs on every tick; the stored value is
    # updated so the banner shows once per change.
    try:
        _timezone_banner_step(conn, notifier)
    except Exception:
        logger.exception("scheduler timezone banner failed")
    logger.info("scheduler tick: finished")


class SchedulerThread(QThread):
    """Owns the scheduler tick loop on its own thread (plan §10.1)."""

    def __init__(
        self,
        conn: Connection,
        on_fired=None,
        gmail_client=None,
        classify=None,
        notifier=None,
    ) -> None:
        super().__init__()
        self._conn = conn
        self._on_fired = on_fired
        self._gmail_client = gmail_client
        self._classify = classify
        self._notifier = notifier
        self._running = True

    def run(self) -> None:  # type: ignore[override]
        while self._running:
            tick(
                self._conn,
                self._on_fired,
                gmail_client=self._gmail_client,
                classify=self._classify,
                notifier=self._notifier,
            )
            # Sleep in small increments so stop() is responsive and shutdown is
            # deterministic (no 30 s wait stuck in msleep).
            slept = 0
            while slept < TICK_SECONDS * 1000 and self._running:
                self.msleep(100)
                slept += 100

    def stop(self) -> None:
        self._running = False
        self.wait()
