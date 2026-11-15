"""Approving a reply sends it into the original thread; a plain draft is sent as before."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import messages as messages_repo
from secretary.store.repos import pending_actions as pa_repo
from secretary.tools.email import email_draft, email_send_prepare


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "rs.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


class _Gmail:
    def __init__(self):
        self.calls = []

    def send_message(self, to_addrs, subject, body, user_id="me", thread_id=None, reply_to_google_id=None):
        self.calls.append({"to": list(to_addrs), "subject": subject, "thread_id": thread_id,
                           "reply_to": reply_to_google_id})
        return {"id": "gm-sent"}


def _approve(conn, gmail, draft_id):
    controller = Controller(conn)
    controller._run_background = lambda fn: fn()
    controller.set_gmail_client(gmail)
    prepared = email_send_prepare(conn, "t", {"draft_ref": str(draft_id)})
    controller.approve_action(str(prepared["pending_id"]))
    return pa_repo.get(conn, prepared["pending_id"])


def test_reply_is_sent_with_the_original_thread_and_message_id():
    conn = _conn()
    try:
        orig = messages_repo.create(
            conn, thread_id="thr-9", from_addr="ravi@example.com", subject="Lunch?", body="?",
            received_at="2026-11-14T08:00:00Z", source="gmail", google_message_id="gm-orig")
        draft = email_draft(conn, "t", {"to": "ravi@example.com", "body": "yes", "reply_to_ref": str(orig)})
        gmail = _Gmail()
        pa = _approve(conn, gmail, draft["draft_id"])
        assert pa["status"] == "executed"
        assert gmail.calls == [{"to": ["ravi@example.com"], "subject": "Re: Lunch?",
                                "thread_id": "thr-9", "reply_to": "gm-orig"}]
    finally:
        conn.close()


def test_plain_draft_is_sent_without_thread_arguments():
    conn = _conn()
    try:
        draft = email_draft(conn, "t", {"to": "ravi@example.com", "subject": "Hi", "body": "hello"})
        gmail = _Gmail()
        _approve(conn, gmail, draft["draft_id"])
        assert gmail.calls[0]["thread_id"] is None and gmail.calls[0]["reply_to"] is None
    finally:
        conn.close()
