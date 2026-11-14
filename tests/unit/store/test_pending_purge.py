"""Expired pending actions are purged after ``expired_retention_days`` (plan §14 daily jobs)."""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import pending_actions as pa_repo


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "p.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


def _iso(days_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_purge_removes_only_old_finished_actions():
    conn = _conn()

    def make(status: str, decided_days_ago: float | None) -> int:
        def op(c):
            pid = pa_repo.create(c, kind="email_send", summary="s", payload_json="{}", expires_at=_iso(-1))
            decided = _iso(decided_days_ago) if decided_days_ago is not None else None
            c.execute("UPDATE pending_actions SET status=?, decided_at=? WHERE id=?", (status, decided, pid))
            return pid

        return conn.write(op)

    old_expired = make("expired", 10)
    fresh_expired = make("expired", 1)
    old_executed = make("executed", 30)  # executed actions are history, never purged here
    waiting = make("waiting", None)

    removed = conn.write(lambda c: pa_repo.purge_expired(c, _iso(7)))
    assert removed == 1
    left = {r[0] for r in conn.read(lambda c: c.execute("SELECT id FROM pending_actions").fetchall())}
    assert left == {fresh_expired, old_executed, waiting}
    assert old_expired not in left
