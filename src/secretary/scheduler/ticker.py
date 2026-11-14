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

import logging
import sqlite3
import time
from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QThread

from secretary.config import load_config
from secretary.integrations.google.calendar import push_pending_events, sync_calendar
from secretary.scheduler.firing import advance, utc_iso
from secretary.scheduler.triage_job import run_triage_job
from secretary.store.db import Connection
from secretary.store.repos import events as events_repo
from secretary.store.repos import inbox as inbox_repo
from secretary.store.repos import pending_actions as pa_repo
from secretary.store.repos import reminders as reminders_repo
from secretary.store.repos import settings as settings_repo

logger = logging.getLogger(__name__)

TICK_SECONDS = 30


def now_utc() -> datetime:
    return datetime.now(UTC)


def _fire_due(conn: sqlite3.Connection) -> list[dict]:
    """Fire all due reminders atomically. Returns the created inbox rows."""
    now = now_utc()
    now_iso = utc_iso(now)
    created: list[dict] = []
    for rem in reminders_repo.list_due(conn, now_iso):
        if not reminders_repo.claim(conn, rem["id"]):
            continue  # already claimed by another tick/process
        try:
            reminders_repo.record_run(conn, rem["id"], rem["next_fire_at"], now_iso)
            # Inbox row is the source of truth; written before the toast.
            inbox_id = inbox_repo.create(
                conn,
                kind="reminder",
                reminder_id=rem["id"],
                title=rem["title"],
                body=rem["body"],
                turn_id=None,
            )
            advance(conn, rem, now)
            created.append(
                {"inbox_id": inbox_id, "reminder_id": rem["id"], "title": rem["title"], "body": rem["body"]}
            )
        except sqlite3.IntegrityError:
            # A run already exists for this (reminder, scheduled_for): release
            # the claim so the reminder is not stuck in 'firing'.
            reminders_repo.release_claim(conn, rem["id"])
    return created


def _repeat_alerts(conn: sqlite3.Connection) -> list[dict]:
    """Unacknowledged for >= 10 minutes and repeat_sent=0 -> one repeat toast.

    Returns the items that need a repeat notification so the caller can toast
    them. Each is marked repeat_sent=1 so it only repeats once.
    """
    cutoff = utc_iso(now_utc() - timedelta(minutes=load_config().notifications.repeat_after_minutes))
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
    now_iso = utc_iso(now_utc())
    conn.execute(
        "UPDATE inbox SET status='unacknowledged', snoozed_until=NULL "
        "WHERE status='snoozed' AND snoozed_until IS NOT NULL AND snoozed_until <= ?",
        (now_iso,),
    )


def _sweeper(conn: sqlite3.Connection) -> None:
    """Expire pending_actions whose expires_at < now; purge old expired ones."""
    now = now_utc()
    pa_repo.expire_waiting(conn, utc_iso(now))
    retention = load_config().pending_actions.expired_retention_days
    pa_repo.purge_expired(conn, utc_iso(now - timedelta(days=retention)))


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


def _sync_due(conn: Connection, sync_minutes: int) -> bool:
    last = settings_repo.get(conn, "google_last_sync")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except ValueError:
        return True
    return now_utc() - last_dt >= timedelta(minutes=sync_minutes)


def _record_calendar_failure(conn: Connection, exc: Exception) -> None:
    settings_repo.set(conn, "google_sync_failed", "1", turn_id="google-sync")
    settings_repo.set(conn, "google_sync_error", str(exc), turn_id="google-sync")


def _calendar_step(conn: Connection, calendar_client, on_events_changed) -> None:
    """Push pending local events, then read-sync if due. Failures are recorded
    for the Settings sync chip and never stop the tick."""
    changed = False
    try:
        if events_repo.list_pending(conn):
            changed = push_pending_events(conn, calendar_client) > 0
    except Exception as exc:
        logger.exception("scheduler calendar push failed")
        _record_calendar_failure(conn, exc)
    try:
        if _sync_due(conn, load_config().google.sync_minutes):
            google_cfg = load_config().google
            result = sync_calendar(
                conn,
                calendar_client,
                "primary",
                window_past_days=google_cfg.window_past_days,
                window_future_days=google_cfg.window_future_days,
            )
            logger.info(
                "scheduler calendar sync: synced=%d deleted=%d",
                result.get("synced", 0),
                result.get("deleted", 0),
            )
            settings_repo.set(
                conn,
                "google_last_sync",
                datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                turn_id="google-sync",
            )
            changed = changed or bool(result.get("synced") or result.get("deleted"))
    except Exception as exc:
        logger.exception("scheduler calendar sync failed")
        _record_calendar_failure(conn, exc)
    if changed and on_events_changed is not None:
        try:
            on_events_changed()
        except Exception:
            logger.exception("scheduler events-changed callback failed")


def tick(
    conn: Connection,
    on_fired=None,
    gmail_client=None,
    calendar_client=None,
    classify=None,
    notifier=None,
    on_events_changed=None,
) -> None:
    """Run one tick: fire due reminders, repeat alerts, snooze expiry, sweeper,
    the Gmail triage job (plan §13.4), Calendar sync (plan §13), and the
    timezone change banner (C-23)."""
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
    # Calendar: push locally created events first (only when some are pending),
    # then read-sync at most every google.sync_minutes.
    if calendar_client is not None:
        _calendar_step(conn, calendar_client, on_events_changed)
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
        calendar_client=None,
        classify=None,
        notifier=None,
        on_events_changed=None,
    ) -> None:
        super().__init__()
        self._on_events_changed = on_events_changed
        self._conn = conn
        self._on_fired = on_fired
        self._gmail_client = gmail_client
        self._calendar_client = calendar_client
        self._classify = classify
        self._notifier = notifier
        self._running = True

    def run(self) -> None:  # type: ignore[override]
        while self._running:
            tick(
                self._conn,
                self._on_fired,
                gmail_client=self._gmail_client,
                calendar_client=self._calendar_client,
                classify=self._classify,
                notifier=self._notifier,
                on_events_changed=self._on_events_changed,
            )
            # Sleep in small increments so stop() is responsive and shutdown is
            # deterministic (no 30 s wait stuck in msleep).
            slept = 0
            while slept < TICK_SECONDS * 1000 and self._running:
                self.msleep(100)
                slept += 100

    def set_google_clients(self, gmail_client, calendar_client) -> None:
        """Swap in Google clients (e.g. right after the user connects Google)."""
        self._gmail_client = gmail_client
        self._calendar_client = calendar_client

    def stop(self) -> None:
        self._running = False
        self.wait()
