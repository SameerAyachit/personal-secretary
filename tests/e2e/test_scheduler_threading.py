"""E2E: scheduler tick runs on a worker thread against the store connection
created on the main thread (the real ``python -m secretary`` composition root).

Bug: the scheduler ticked on a worker thread and called ``conn.execute()`` on
the connection opened on the main thread. SQLite raised::

    sqlite3.ProgrammingError: SQLite objects created in a thread can only be
    used in that same thread.

So no reminder ever fired. Plan §5.4: one writer connection behind an RLock,
accessed through ``Connection.write``/``read``/``execute`` only, opened with
``check_same_thread=False`` so threads may share it.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import secretary.scheduler.ticker as ticker_mod
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import inbox as inbox_repo
from secretary.store.repos import reminders as reminders_repo


def _conn(tmp_path: Path) -> Connection:
    db = tmp_path / "sched.db"
    conn = Connection(db)
    migrate(conn._con, migrations_folder(), lambda: None)
    return conn


def test_scheduler_fires_reminder_from_worker_thread(tmp_path, monkeypatch):
    """Real composition root: a worker thread uses the main-thread connection."""
    # A reminder due right now.
    conn = _conn(tmp_path)
    reminders_repo.create(
        conn,
        task_id=None,
        title="drink water",
        body="hydrate",
        kind="once",
        tz="Asia/Kolkata",
        rule_json=None,
        next_fire_at="2020-01-01T00:00:00Z",
        priority=0,
        idempotency_key=None,
        turn_id="e2e",
    )

    # Speed up the tick so the test does not wait 30 s.
    monkeypatch.setattr(ticker_mod, "TICK_SECONDS", 0.05)

    fired: list[dict] = []
    stop = False

    def tick_loop():
        while not stop:
            ticker_mod.tick(conn, on_fired=fired.extend)

    thread = threading.Thread(target=tick_loop, daemon=True)
    try:
        thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not fired:
            time.sleep(0.05)
    finally:
        stop = True
        thread.join()

    assert fired, "no reminder fired on the worker thread"
    rows = inbox_repo.list_unacknowledged(conn)
    assert any(r["title"] == "drink water" for r in rows), rows
