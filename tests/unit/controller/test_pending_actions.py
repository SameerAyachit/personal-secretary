"""Controller pending-actions approval/execution (plan §3.5, §8.2, §995)."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from secretary.controller import Controller
from secretary.integrations.google.gmail import GmailError, GmailPermissionError
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import messages as messages_repo
from secretary.store.repos import pending_actions as pa_repo
from secretary.tools.email import email_send_prepare


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "pa.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


def _seed_draft(conn):
    return messages_repo.create(
        conn, from_addr="me@example.com", to_addrs='["ravi@example.com"]',
        subject="Draft for ravi", body="Hello Ravi",
        received_at="2026-11-09T08:00:00+00:00", source="draft", turn_id="seed")


class _FakeGmail:
    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[tuple[list[str], str, str]] = []
        self.error = error

    def send_message(self, to_addrs, subject, body, user_id="me"):
        if self.error is not None:
            raise self.error
        self.sent.append((list(to_addrs), subject, body))
        return {"id": "gm-1"}


def _controller(conn, gmail=None):
    controller = Controller(conn)
    controller._run_background = lambda fn: fn()  # run the send inline in tests
    if gmail is not None:
        controller.set_gmail_client(gmail)
    return controller


def test_approve_send_executes_after_reverify():
    conn = _conn()
    try:
        gmail = _FakeGmail()
        controller = _controller(conn, gmail)
        draft_id = _seed_draft(conn)
        prepared = email_send_prepare(conn, "t-1", {"draft_ref": str(draft_id)})
        assert prepared["status"] == "waiting"
        pending_id = prepared["pending_id"]

        controller.approve_action(str(pending_id))
        pa = pa_repo.get(conn, pending_id)
        assert pa["status"] == "executed"
        assert gmail.sent == [(["ravi@example.com"], "Draft for ravi", "Hello Ravi")]
        assert json.loads(pa["result_json"])["gmail_id"] == "gm-1"
    finally:
        conn.close()


def test_approve_send_twice_sends_once():
    conn = _conn()
    try:
        gmail = _FakeGmail()
        controller = _controller(conn, gmail)
        prepared = email_send_prepare(conn, "t-1", {"draft_ref": str(_seed_draft(conn))})
        controller.approve_action(str(prepared["pending_id"]))
        controller.approve_action(str(prepared["pending_id"]))
        assert len(gmail.sent) == 1
    finally:
        conn.close()


def test_approve_send_without_google_fails_with_message():
    conn = _conn()
    try:
        controller = _controller(conn, None)
        prepared = email_send_prepare(conn, "t-1", {"draft_ref": str(_seed_draft(conn))})
        statuses: list[str] = []
        controller.turn_status.connect(statuses.append)
        controller.approve_action(str(prepared["pending_id"]))
        pa = pa_repo.get(conn, prepared["pending_id"])
        assert pa["status"] == "failed"
        assert "Google" in json.loads(pa["result_json"])["reason"]
        assert any("Google" in s for s in statuses)
    finally:
        conn.close()


def test_approve_send_permission_error_says_reconnect():
    conn = _conn()
    try:
        controller = _controller(conn, _FakeGmail(GmailPermissionError("403")))
        prepared = email_send_prepare(conn, "t-1", {"draft_ref": str(_seed_draft(conn))})
        controller.approve_action(str(prepared["pending_id"]))
        pa = pa_repo.get(conn, prepared["pending_id"])
        assert pa["status"] == "failed"
        assert "Reconnect Google" in json.loads(pa["result_json"])["reason"]
    finally:
        conn.close()


def test_approve_send_gmail_error_marks_failed():
    conn = _conn()
    try:
        controller = _controller(conn, _FakeGmail(GmailError("boom")))
        prepared = email_send_prepare(conn, "t-1", {"draft_ref": str(_seed_draft(conn))})
        controller.approve_action(str(prepared["pending_id"]))
        pa = pa_repo.get(conn, prepared["pending_id"])
        assert pa["status"] == "failed"
    finally:
        conn.close()


def test_send_summary_names_real_recipient_and_subject():
    conn = _conn()
    try:
        prepared = email_send_prepare(conn, "t-1", {"draft_ref": str(_seed_draft(conn))})
        assert "ravi@example.com" in prepared["summary"]
        assert "Draft for ravi" in prepared["summary"]
        assert "me@example.com" not in prepared["summary"]
    finally:
        conn.close()


def test_approve_send_refuses_when_draft_changed():
    conn = _conn()
    try:
        gmail = _FakeGmail()
        controller = _controller(conn, gmail)
        draft_id = _seed_draft(conn)
        prepared = email_send_prepare(conn, "t-1", {"draft_ref": str(draft_id)})
        pending_id = prepared["pending_id"]

        conn._con.execute(
            "UPDATE email_messages SET body='Tampered', updated_at=? WHERE id=?",
            ("2026-11-09T09:00:00Z", draft_id),
        )

        controller.approve_action(str(pending_id))
        pa = pa_repo.get(conn, pending_id)
        assert pa["status"] == "failed"
        assert json.loads(pa["result_json"])["reason"] == "draft changed since approval"
        assert gmail.sent == []
    finally:
        conn.close()


def test_approve_expired_action_refused():
    conn = _conn()
    try:
        controller = Controller(conn)
        pending_id = pa_repo.create(
            conn, kind="email.send", summary="expired send",
            payload_json=json.dumps({}), expires_at="2020-01-01T00:00:00Z", turn_id="t-1")
        controller.approve_action(str(pending_id))
        pa = pa_repo.get(conn, pending_id)
        assert pa["status"] == "expired"
    finally:
        conn.close()


def test_pending_actions_highlights_new_recipients():
    conn = _conn()
    try:
        controller = Controller(conn)
        messages_repo.create(
            conn, from_addr="boss@example.com", to_addrs='["me@example.com"]',
            subject="Old", body="Old mail", received_at="2026-11-09T08:00:00+00:00", turn_id="s")
        draft_id = messages_repo.create(
            conn, from_addr="me@example.com", to_addrs='["ravi@example.com", "boss@example.com"]',
            subject="Draft", body="Body", received_at="2026-11-09T09:00:00+00:00", source="draft", turn_id="s")
        email_send_prepare(conn, "t-1", {"draft_ref": str(draft_id)})
        rows = controller.list_pending_actions()
        assert len(rows) == 1
        row = rows[0]
        assert row["recipients"] == ["ravi@example.com", "boss@example.com"]
        assert row["new_recipients"] == ["ravi@example.com"]
        assert row["body"] == "Body"
        assert row["subject"] == "Draft"
    finally:
        conn.close()


def test_reject_action():
    conn = _conn()
    try:
        controller = Controller(conn)
        draft_id = _seed_draft(conn)
        prepared = email_send_prepare(conn, "t-1", {"draft_ref": str(draft_id)})
        controller.reject_action(str(prepared["pending_id"]))
        pa = pa_repo.get(conn, prepared["pending_id"])
        assert pa["status"] == "rejected"
    finally:
        conn.close()


def test_approve_unknown_action_is_noop():
    conn = _conn()
    try:
        controller = Controller(conn)
        controller.approve_action("999999")  # must not raise
        controller.approve_action("not-a-number")  # must not raise
    finally:
        conn.close()
