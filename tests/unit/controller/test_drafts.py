"""Drafts: list, request send, discard, and mark sent (ADR-005)."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import messages as messages_repo
from secretary.store.repos import pending_actions as pa_repo
from secretary.tools.email import email_send_prepare


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "d.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


def _draft(conn, subject="Hello", to='["ravi@example.com"]'):
    return messages_repo.create(
        conn, from_addr="me", to_addrs=to, subject=subject, body="Body",
        received_at="2026-11-09T08:00:00+00:00", source="draft", turn_id="s")


def test_list_drafts_returns_only_drafts_with_recipients():
    conn = _conn()
    try:
        messages_repo.create(
            conn, from_addr="boss@example.com", to_addrs='["me@example.com"]',
            subject="Inbound", body="x", received_at="2026-11-09T07:00:00+00:00", turn_id="s")
        draft_id = _draft(conn)
        rows = Controller(conn).list_drafts()
        assert [r["id"] for r in rows] == [draft_id]
        assert rows[0]["recipients"] == ["ravi@example.com"]
        assert rows[0]["subject"] == "Hello"
        assert rows[0]["send_requested"] is False
    finally:
        conn.close()


def test_queue_draft_send_creates_one_waiting_action():
    conn = _conn()
    try:
        controller = Controller(conn)
        draft_id = _draft(conn)
        signals: list[int] = []
        controller.approvals_changed.connect(lambda: signals.append(1))
        controller.queue_draft_send(draft_id)
        controller.queue_draft_send(draft_id)  # second click must not duplicate
        waiting = pa_repo.list_waiting(conn, now_iso="2000-01-01T00:00:00Z")
        assert len(waiting) == 1
        assert "ravi@example.com" in waiting[0]["summary"]
        assert controller.list_drafts()[0]["send_requested"] is True
        assert signals
    finally:
        conn.close()


def test_discard_draft_removes_it():
    conn = _conn()
    try:
        controller = Controller(conn)
        draft_id = _draft(conn)
        controller.discard_draft(draft_id)
        assert controller.list_drafts() == []
    finally:
        conn.close()


def test_discard_draft_ignores_non_drafts():
    conn = _conn()
    try:
        controller = Controller(conn)
        inbound = messages_repo.create(
            conn, from_addr="boss@example.com", to_addrs='["me@example.com"]',
            subject="Inbound", body="x", received_at="2026-11-09T07:00:00+00:00", turn_id="s")
        controller.discard_draft(inbound)
        assert messages_repo.get(conn, inbound) is not None
    finally:
        conn.close()


def test_sent_draft_leaves_drafts_list():
    class _Gmail:
        def send_message(self, to_addrs, subject, body, user_id="me"):
            return {"id": "g1"}

    conn = _conn()
    try:
        controller = Controller(conn)
        controller._run_background = lambda fn: fn()
        controller.set_gmail_client(_Gmail())
        draft_id = _draft(conn)
        prepared = email_send_prepare(conn, "t", {"draft_ref": str(draft_id)})
        controller.approve_action(str(prepared["pending_id"]))
        assert controller.list_drafts() == []
        assert messages_repo.get(conn, draft_id)["source"] == "sent"
    finally:
        conn.close()
