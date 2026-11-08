"""Tests for email_send tool: Class C never executes, goes to pending_actions (plan §8.2)."""

import sqlite3
import tempfile
from pathlib import Path

from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.tools.email import email_send_prepare


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "e.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")

    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


def test_email_send_prepares_pending_action_waiting():
    conn = _conn()
    try:
        result = email_send_prepare(conn, "turn-1", {"draft_ref": "draft-42"})
        assert result["status"] == "waiting"
        assert result["summary"] == "Send email draft draft-42"
        assert result["note"].startswith("Class C")
        assert "pending_id" in result
        assert result["expires_at"] is not None
    finally:
        conn.close()
