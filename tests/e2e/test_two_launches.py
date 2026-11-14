"""R1: turn ids must be unique across app launches.

Idempotency keys hash the turn id. If ``Controller`` restarts its counter at 0
on every launch, the same request in a new session maps to the previous
session's reminder and no new reminder is created.
"""

from __future__ import annotations

from datetime import UTC, datetime

from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.tools import reminders as reminders_tools
from secretary.tools.reminders import reminder_create


def _conn(tmp_path) -> Connection:
    conn = Connection(tmp_path / "launch.db")
    migrate(conn._con, migrations_folder(), lambda: None)
    return conn


def test_controller_turn_ids_differ_between_launches(tmp_path):
    conn = _conn(tmp_path)
    first = Controller(conn)._new_turn_id()
    second = Controller(conn)._new_turn_id()
    assert first != second


def test_same_request_in_two_launches_creates_two_reminders(tmp_path, monkeypatch):
    monkeypatch.setattr(
        reminders_tools, "_utc_now", lambda: datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
    )
    conn = _conn(tmp_path)
    args = {"title": "drink water", "when_text": "in 10 minutes"}
    ids = []
    for _ in range(2):
        turn_id = Controller(conn)._new_turn_id()
        out = reminder_create(conn, turn_id, dict(args))
        assert "error" not in out
        ids.append(out["reminder_id"])
        # Fire/finish the reminder so the time-window dedupe cannot mask R1.
        conn.execute("UPDATE reminders SET status='done' WHERE id=?", (out["reminder_id"],))
    assert ids[0] != ids[1]
