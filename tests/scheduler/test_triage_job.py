"""Tests for the Gmail triage background job (plan §13.4).

The job syncs recent Gmail messages into the local store and classifies
unread messages into category/urgency/suggested_action enums. Both the
Gmail client and the classifier are injectable fakes here: real
credentials and the LLM-backed classifier are human-gated.
"""

from __future__ import annotations

import base64
import sqlite3
import tempfile
from pathlib import Path

from secretary.scheduler.ticker import tick
from secretary.scheduler.triage_job import run_triage_job, sync_gmail_messages
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import messages as messages_repo


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def _message(message_id: str, subject: str, from_addr: str, date: str, unread: bool = True) -> dict:
    return {
        "id": message_id,
        "threadId": f"thread-{message_id}",
        "labelIds": ["UNREAD", "INBOX"] if unread else ["INBOX"],
        "payload": {
            "headers": [
                {"name": "From", "value": from_addr},
                {"name": "To", "value": "me@example.com"},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": date},
            ],
            "body": {"data": _b64(f"body of {subject}")},
        },
    }


class _FakeGmailClient:
    def __init__(self, messages: list[dict]) -> None:
        self._messages = {m["id"]: m for m in messages}
        self.list_calls = 0
        self.get_calls: list[str] = []

    def list_messages(self, max_results: int = 50, query: str | None = None, page_token: str | None = None) -> dict:
        self.list_calls += 1
        return {"messages": [{"id": m["id"]} for m in self._messages.values()]}

    def get_message(self, message_id: str, format: str = "full") -> dict:
        self.get_calls.append(message_id)
        msg = self._messages.get(message_id)
        if msg is None:
            raise RuntimeError("not found")
        return msg


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "triage.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


def _store_message(con: sqlite3.Connection, google_id: str, subject: str, from_addr: str) -> None:
    messages_repo.create(
        con,
        thread_id=f"thread-{google_id}",
        from_addr=from_addr,
        to_addrs='["me@example.com"]',
        subject=subject,
        body=f"body of {subject}",
        received_at="2026-11-11T09:00:00+00:00",
        is_read=0,
        source="gmail",
        google_message_id=google_id,
        turn_id="triage-job",
    )


def _classify(outcomes: dict[str, dict]):
    calls: list[dict] = []

    def classify(payload: dict) -> dict:
        calls.append(payload)
        return outcomes[payload["subject"]]

    return classify, calls


def test_sync_gmail_messages_stores_new_messages():
    gmail = _FakeGmailClient([
        _message("gm-1", "Project update", "alice@example.com", "Wed, 11 Nov 2026 09:00:00 +0000"),
        _message("gm-2", "Newsletter", "news@example.com", "Tue, 10 Nov 2026 08:00:00 +0000", unread=False),
    ])
    conn = _conn()
    try:
        stored = sync_gmail_messages(conn, gmail, "triage-job")
        assert stored == 2
        assert gmail.list_calls == 1
        assert gmail.get_calls == ["gm-1", "gm-2"]

        row = conn.execute("SELECT * FROM email_messages WHERE google_message_id=?", ("gm-1",)).fetchone()
        assert row is not None
        assert row["from_addr"] == "alice@example.com"
        assert row["subject"] == "Project update"
        assert row["body"] == "body of Project update"
        assert row["received_at"] == "2026-11-11T09:00:00Z"
        assert row["is_read"] == 0
        assert row["source"] == "gmail"
        assert row["thread_id"] == "thread-gm-1"

        row2 = conn.execute("SELECT * FROM email_messages WHERE google_message_id=?", ("gm-2",)).fetchone()
        assert row2 is not None and row2["is_read"] == 1
    finally:
        conn.close()


def test_sync_gmail_messages_skips_already_stored():
    gmail = _FakeGmailClient([_message("gm-1", "One", "a@example.com", "Wed, 11 Nov 2026 09:00:00 +0000")])
    conn = _conn()
    try:
        assert sync_gmail_messages(conn, gmail, "triage-job") == 1
        assert sync_gmail_messages(conn, gmail, "triage-job") == 0  # dedup by google_message_id
        assert conn.execute("SELECT COUNT(*) FROM email_messages").fetchone()[0] == 1
    finally:
        conn.close()


def test_sync_gmail_messages_get_failure_does_not_abort():
    gmail = _FakeGmailClient([
        _message("gm-1", "One", "a@example.com", "Wed, 11 Nov 2026 09:00:00 +0000"),
        _message("gm-2", "Two", "b@example.com", "Wed, 11 Nov 2026 09:00:00 +0000"),
    ])

    def get_message(message_id: str, format: str = "full") -> dict:
        if message_id == "gm-2":
            raise RuntimeError("boom")
        return gmail._messages[message_id]

    gmail.get_message = get_message  # type: ignore[method-assign]
    conn = _conn()
    try:
        stored = sync_gmail_messages(conn, gmail, "triage-job")
        assert stored == 1  # gm-2 failed, gm-1 stored
    finally:
        conn.close()


def test_run_triage_job_classifies_and_stores():
    classify, calls = _classify({
        "One": {"category": "work", "urgency": "high", "suggested_action": "reply"},
        "Two": {"category": "newsletter", "urgency": "low", "suggested_action": "archive"},
    })
    conn = _conn()
    try:
        conn.write(lambda con: _store_message(con, "gm-1", "One", "a@example.com"))
        conn.write(lambda con: _store_message(con, "gm-2", "Two", "b@example.com"))
        summary = run_triage_job(conn, classify=classify, limit=10)
        assert summary == {
            "synced": 0,
            "triaged": 2,
            "by_category": {"work": 1, "newsletter": 1},
            "by_urgency": {"high": 1, "low": 1},
        }
        rows = [
            tuple(r)
            for r in conn.execute(
                "SELECT message_id, category, urgency, suggested_action FROM triage_results ORDER BY message_id"
            ).fetchall()
        ]
        assert rows == [(1, "work", "high", "reply"), (2, "newsletter", "low", "archive")]
        assert len(calls) == 2  # one classify call per message
    finally:
        conn.close()


def test_run_triage_job_invalid_results_skipped():
    classify, _calls = _classify({
        "One": {"category": "work", "urgency": "high", "suggested_action": "reply"},
        "Two": {"category": "not-a-category", "urgency": "low", "suggested_action": "archive"},
    })
    conn = _conn()
    try:
        conn.write(lambda con: _store_message(con, "gm-1", "One", "a@example.com"))
        conn.write(lambda con: _store_message(con, "gm-2", "Two", "b@example.com"))
        summary = run_triage_job(conn, classify=classify, limit=10)
        assert summary["triaged"] == 1
        assert summary["by_category"] == {"work": 1}
        rows = [r[0] for r in conn.execute("SELECT message_id FROM triage_results").fetchall()]
        assert rows == [1]
    finally:
        conn.close()


def test_run_triage_job_classify_exception_does_not_stop_others():
    def classify(payload: dict) -> dict:
        if payload["subject"] == "One":
            raise RuntimeError("classifier down")
        return {"category": "personal", "urgency": "normal", "suggested_action": "read"}

    conn = _conn()
    try:
        conn.write(lambda con: _store_message(con, "gm-1", "One", "a@example.com"))
        conn.write(lambda con: _store_message(con, "gm-2", "Two", "b@example.com"))
        summary = run_triage_job(conn, classify=classify, limit=10)
        assert summary["triaged"] == 1
        assert [r[0] for r in conn.execute("SELECT message_id FROM triage_results").fetchall()] == [2]
    finally:
        conn.close()


def test_run_triage_job_noop_without_dependencies():
    conn = _conn()
    try:
        summary = run_triage_job(conn)
        assert summary == {"synced": 0, "triaged": 0, "by_category": {}, "by_urgency": {}}
    finally:
        conn.close()


def test_tick_runs_triage_job():
    classify, _calls = _classify({
        "One": {"category": "work", "urgency": "high", "suggested_action": "reply"},
    })
    gmail = _FakeGmailClient([_message("gm-1", "One", "a@example.com", "Wed, 11 Nov 2026 09:00:00 +0000")])
    conn = _conn()
    try:
        tick(conn, gmail_client=gmail, classify=classify)
        assert conn.execute("SELECT COUNT(*) FROM email_messages WHERE google_message_id='gm-1'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM triage_results").fetchone()[0] == 1
    finally:
        conn.close()


def test_tick_without_job_deps_still_works():
    conn = _conn()
    try:
        tick(conn)  # no-op job steps, same as before the triage job existed
    finally:
        conn.close()
