"""Read-only audit of chat-made items (scripts/check_utc_bug.py)."""

from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import audit, events, reminders


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "a.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


def test_lists_only_items_a_chat_turn_created():
    conn = _conn()
    try:
        reminders.create(conn, task_id=None, title="chat reminder", body="", kind="once", tz="Asia/Kolkata",
                         rule_json=None, next_fire_at="2026-11-20T03:30:00+00:00", priority=0,
                         idempotency_key="k1", turn_id="turn-1")
        reminders.create(conn, task_id=None, title="ui reminder", body="", kind="once", tz="Asia/Kolkata",
                         rule_json=None, next_fire_at="2026-11-20T03:30:00+00:00", priority=0,
                         idempotency_key="k2", turn_id=None)
        events.create(conn, title="chat event", start_at="2026-11-21T03:30:00+00:00",
                      end_at="2026-11-21T04:30:00+00:00", tz="Asia/Kolkata", turn_id="turn-1")
        events.create(conn, title="google event", start_at="2026-11-21T03:30:00+00:00",
                      end_at=None, tz="Asia/Kolkata", turn_id=None)
        future = datetime(2100, 1, 1, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        found = conn.read(lambda con: audit.chat_items_before(con, future))
        assert [r["title"] for r in found["reminders"]] == ["chat reminder"]
        assert [e["title"] for e in found["events"]] == ["chat event"]
        assert conn.read(lambda con: audit.chat_items_before(con, "2000-01-01T00:00:00Z")) == {
            "reminders": [], "events": []}
    finally:
        conn.close()


def test_script_is_read_only_and_runs(capsys):
    spec = importlib.util.spec_from_file_location(
        "check_utc_bug", Path(__file__).parents[3] / "scripts" / "check_utc_bug.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    conn = _conn()
    db = conn._path
    conn.close()
    assert module.main(["x", str(db)]) == 0
    assert "0 item(s)" in capsys.readouterr().out
    assert module.main(["x", str(db) + ".missing"]) == 1
