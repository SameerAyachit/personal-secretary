"""Tests for the timezone change banner (plan C-23).

When the system time zone changes, the scheduler tick shows one banner:
an inbox item plus a toast. The banner shows once per change; the stored
signature is updated so it does not repeat.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from secretary.scheduler.ticker import _tz_signature, tick
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import settings as settings_repo


class _FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []

    def notify(self, title: str, body: str, priority: bool = False) -> None:
        self.calls.append((title, body, priority))


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "tz.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


def test_banner_shown_when_timezone_changes():
    conn = _conn()
    notifier = _FakeNotifier()
    settings_repo.set(conn._con, "system_timezone", "stale:signature:of:the:past")
    tick(conn, notifier=notifier)

    rows = [
        tuple(r)
        for r in conn.execute(
            "SELECT title, body, kind FROM inbox WHERE kind='system'"
        ).fetchall()
    ]
    assert rows == [
        (
            "Time zone changed",
            "Your system time zone changed; reminder times now follow the new time zone.",
            "system",
        )
    ]
    assert notifier.calls == [
        (
            "Time zone changed",
            "Your system time zone changed; reminder times now follow the new time zone.",
            True,
        )
    ]
    assert settings_repo.get(conn._con, "system_timezone") == _tz_signature()


def test_banner_not_repeated_when_unchanged():
    conn = _conn()
    notifier = _FakeNotifier()
    settings_repo.set(conn._con, "system_timezone", _tz_signature())
    tick(conn, notifier=notifier)

    assert notifier.calls == []
    assert (
        conn.execute("SELECT count(*) FROM inbox WHERE kind='system'").fetchone()[0]
        == 0
    )
    assert settings_repo.get(conn._con, "system_timezone") == _tz_signature()


def test_banner_not_shown_on_first_run():
    conn = _conn()
    notifier = _FakeNotifier()
    tick(conn, notifier=notifier)

    assert notifier.calls == []
    assert (
        conn.execute("SELECT count(*) FROM inbox WHERE kind='system'").fetchone()[0]
        == 0
    )
    assert settings_repo.get(conn._con, "system_timezone") == _tz_signature()
