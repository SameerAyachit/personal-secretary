"""research_briefs repo and migration 008."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import research_briefs as repo


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "r.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


def test_job_lifecycle_running_then_done():
    conn = _conn()
    bid = conn.write(lambda c: repo.create(c, "aqi prediction"))
    assert conn.read(lambda c: repo.get(c, bid))["status"] == "running"
    conn.write(lambda c: repo.finish(c, bid, "Brief text.", [{"url": "https://e.com", "title": "E"}], partial=True))
    row = conn.read(lambda c: repo.get(c, bid))
    assert (row["status"], row["brief"], row["partial"]) == ("done", "Brief text.", 1)
    assert json.loads(row["sources_json"]) == [{"url": "https://e.com", "title": "E"}]
    assert row["finished_at"]


def test_failure_keeps_the_reason():
    conn = _conn()
    bid = conn.write(lambda c: repo.create(c, "t"))
    conn.write(lambda c: repo.fail(c, bid, "provider down"))
    row = conn.read(lambda c: repo.get(c, bid))
    assert (row["status"], row["error"]) == ("failed", "provider down")


def test_list_recent_is_newest_first_and_stale_jobs_are_failed_at_startup():
    conn = _conn()
    first = conn.write(lambda c: repo.create(c, "one"))
    second = conn.write(lambda c: repo.create(c, "two"))
    conn.write(lambda c: repo.finish(c, first, "done", [], partial=False))
    assert [r["id"] for r in conn.read(lambda c: repo.list_recent(c, 10))] == [second, first]
    assert conn.write(repo.fail_stale_running) == 1  # only the one still running
    assert conn.read(lambda c: repo.get(c, second))["error"].startswith("Interrupted")
    assert conn.read(lambda c: repo.get(c, first))["status"] == "done"
