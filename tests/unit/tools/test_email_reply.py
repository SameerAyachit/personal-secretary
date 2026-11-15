"""email_draft with reply_to_ref links the draft to the original message's thread."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import messages as messages_repo
from secretary.tools.email import _send_summary, email_draft


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "m.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


def _original(conn):
    return messages_repo.create(
        conn, thread_id="thr-9", from_addr="Ravi <ravi@example.com>", to_addrs='["me@example.com"]',
        subject="Lunch on Friday?", body="Are you free?", received_at="2026-11-14T08:00:00Z",
        source="gmail", google_message_id="gm-orig")


def test_reply_draft_joins_the_thread_and_defaults_the_subject():
    conn = _conn()
    try:
        orig = _original(conn)
        out = email_draft(conn, "t", {"to": "ravi@example.com", "body": "Yes, 1pm works.",
                                      "reply_to_ref": str(orig)})
        assert out["subject"] == "Re: Lunch on Friday?"
        draft = messages_repo.get(conn, out["draft_id"])
        assert draft["thread_id"] == "thr-9" and draft["reply_to_id"] == orig and draft["source"] == "draft"
        assert "Re: Lunch on Friday?" in _send_summary(draft) and "reply" in _send_summary(draft).lower()
    finally:
        conn.close()


def test_reply_keeps_an_explicit_subject_and_does_not_double_prefix():
    conn = _conn()
    try:
        orig = _original(conn)
        out = email_draft(conn, "t", {"to": "r@example.com", "body": "ok", "subject": "Re: Lunch on Friday?",
                                      "reply_to_ref": str(orig)})
        assert out["subject"] == "Re: Lunch on Friday?"
        out = email_draft(conn, "t", {"to": "r@example.com", "body": "ok", "subject": "Something else",
                                      "reply_to_ref": str(orig)})
        assert out["subject"] == "Something else"
    finally:
        conn.close()


def test_unknown_reply_target_is_a_plain_error_and_saves_nothing():
    conn = _conn()
    try:
        out = email_draft(conn, "t", {"to": "r@example.com", "body": "ok", "reply_to_ref": "999"})
        assert "error" in out and "not found" in out["error"].lower()
        out = email_draft(conn, "t", {"to": "r@example.com", "body": "ok", "reply_to_ref": "abc"})
        assert "error" in out
        assert conn.execute("SELECT COUNT(*) FROM email_messages").fetchone()[0] == 0
    finally:
        conn.close()


def test_plain_draft_is_unchanged():
    conn = _conn()
    try:
        out = email_draft(conn, "t", {"to": "r@example.com", "subject": "Hi", "body": "hello"})
        draft = messages_repo.get(conn, out["draft_id"])
        assert draft["reply_to_id"] is None and "reply" not in _send_summary(draft).lower()
    finally:
        conn.close()
