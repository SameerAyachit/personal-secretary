"""Draft wording: drafts live in Approvals > Drafts; there is no outbox."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from secretary.agent.loop import SYSTEM_PROMPT
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.tools.email import email_draft


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "t.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


def test_draft_note_points_to_approvals_not_outbox():
    conn = _conn()
    try:
        out = email_draft(conn, "t", {"to": "a@b.com", "subject": "S", "body": "B"})
        assert "Approvals" in out["note"]
        assert "Drafts" in out["note"]
        assert "outbox" not in out["note"].lower()
    finally:
        conn.close()


def test_system_prompt_forbids_outbox_claims():
    assert "no outbox" in SYSTEM_PROMPT.lower()
    assert "Approvals" in SYSTEM_PROMPT
