"""Tests for email triage (plan §3.5): enum classification stored locally."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

import secretary.tools.email as email_mod
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import messages as messages_repo
from secretary.tools.email import triage_run


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "triage.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


def _seed(conn):
    messages_repo.create(
        conn, from_addr="billing@example.com", to_addrs='["me@example.com"]',
        subject="Invoice March", body="Please pay invoice 100 by Friday.",
        received_at="2026-11-09T08:00:00+00:00", turn_id="s1")
    messages_repo.create(
        conn, from_addr="news@example.com", to_addrs='["me@example.com"]',
        subject="Weekly news", body="Read all about it here.",
        received_at="2026-11-09T09:00:00+00:00", turn_id="s2")
    messages_repo.create(
        conn, from_addr="boss@example.com", to_addrs='["me@example.com"]',
        subject="Offsite", body="Team offsite next week, please reply.",
        received_at="2026-11-09T10:00:00+00:00", turn_id="s3")


def _classify(message):
    subj = (message.get("subject") or "").lower()
    if "invoice" in subj:
        return {"category": "invoice", "urgency": "high", "suggested_action": "reply"}
    if "news" in subj:
        return {"category": "newsletter", "urgency": "low", "suggested_action": "archive"}
    return {"category": "work", "urgency": "normal", "suggested_action": "read"}


def test_triage_run_classifies_and_stores(monkeypatch):
    monkeypatch.setattr(email_mod, "_classify", _classify)
    conn = _conn()
    try:
        _seed(conn)
        result = triage_run(conn, "t-1", {"scope": "inbox"})
        assert result["scope"] == "inbox"
        assert result["triaged"] == 3
        assert result["by_category"] == {"invoice": 1, "newsletter": 1, "work": 1}
        assert result["by_urgency"] == {"high": 1, "low": 1, "normal": 1}
        rows = messages_repo.list_triage_results(conn)
        assert len(rows) == 3
        inv = next(r for r in rows if r["subject"] == "Invoice March")
        assert inv["category"] == "invoice"
        assert inv["urgency"] == "high"
        assert inv["suggested_action"] == "reply"
    finally:
        conn.close()


def test_triage_run_deduplicates_on_re_run(monkeypatch):
    monkeypatch.setattr(email_mod, "_classify", _classify)
    conn = _conn()
    try:
        _seed(conn)
        triage_run(conn, "t-1", {"scope": "inbox"})
        triage_run(conn, "t-2", {"scope": "inbox"})
        rows = messages_repo.list_triage_results(conn)
        assert len(rows) == 3  # upsert by message_id: no duplicates
    finally:
        conn.close()


def test_triage_run_unconfigured_errors():
    conn = _conn()
    try:
        previous = email_mod._classify
        email_mod._classify = None
        try:
            assert triage_run(conn, "t-1", {"scope": "inbox"}) == {
                "error": "triage classify callback not configured", "scope": "inbox",
            }
        finally:
            email_mod._classify = previous
    finally:
        conn.close()


def test_triage_run_unknown_scope_raises(monkeypatch):
    monkeypatch.setattr(email_mod, "_classify", _classify)
    conn = _conn()
    try:
        with pytest.raises(ValidationError):
            triage_run(conn, "t-1", {"scope": "everything"})
    finally:
        conn.close()


def test_triage_run_invalid_enum_skipped(monkeypatch):
    def bad(message):
        return {"category": "not-a-category", "urgency": "normal", "suggested_action": "read"}

    monkeypatch.setattr(email_mod, "_classify", bad)
    conn = _conn()
    try:
        _seed(conn)
        result = triage_run(conn, "t-1", {"scope": "inbox"})
        assert result["triaged"] == 0
        assert messages_repo.list_triage_results(conn) == []
    finally:
        conn.close()
