"""The tick runs the update check through an injected function and never fails because of it."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from secretary.scheduler.ticker import tick
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "t.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


def test_tick_calls_the_update_checker_and_signals_a_new_release():
    conn = _conn()
    calls: list[object] = []
    notified: list[dict] = []

    def checker(con):
        calls.append(con)
        return {"tag": "v9.0.0", "url": "https://github.com/o/r/releases/tag/v9.0.0"}

    tick(conn, update_checker=checker, on_update_found=notified.append)
    assert len(calls) == 1 and notified == [{"tag": "v9.0.0", "url": "https://github.com/o/r/releases/tag/v9.0.0"}]


def test_tick_without_a_checker_makes_no_update_call():
    conn = _conn()
    tick(conn)  # existing behaviour: nothing network-related runs


def test_a_failing_checker_never_stops_the_tick():
    conn = _conn()

    def checker(con):
        raise RuntimeError("boom")

    tick(conn, update_checker=checker)  # must not raise
