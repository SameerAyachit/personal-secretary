"""A cancelled (soft-deleted) reminder must never fire, from the ticker or catch-up."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from secretary.scheduler.catchup import catch_up
from secretary.scheduler.ticker import tick
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import reminders as reminders_repo
from secretary.tools.reminders import reminder_cancel


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "c.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


def _overdue_cancelled(conn) -> int:
    rid = reminders_repo.create(
        conn, task_id=None, title="drink water", body="", kind="once", tz="UTC",
        rule_json=None, next_fire_at="2020-01-01T00:00:00+00:00",
    )
    assert "error" not in reminder_cancel(conn, "t", {"reminder_ref": str(rid)})
    return rid


def test_ticker_does_not_fire_a_cancelled_reminder():
    conn = _conn()
    _overdue_cancelled(conn)
    fired: list = []
    tick(conn, on_fired=fired.extend)
    assert fired == []
    assert conn.execute("SELECT count(*) FROM inbox").fetchone()[0] == 0


def test_catch_up_does_not_report_a_cancelled_reminder():
    conn = _conn()
    _overdue_cancelled(conn)
    assert catch_up(conn)["count"] == 0
    assert conn.execute("SELECT count(*) FROM inbox").fetchone()[0] == 0
