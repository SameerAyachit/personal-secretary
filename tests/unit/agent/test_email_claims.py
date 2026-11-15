"""The agent must never claim it saved or sent an email unless a tool did (plan section 8)."""

from __future__ import annotations

import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from secretary.agent.loop import run_turn
from secretary.agent.router import Router
from secretary.llm.base import LLMResponse, ToolCall
from secretary.llm.fake import FakeLLM
from secretary.llm.limiter import Limiter
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import messages as messages_repo
from secretary.tools.email import EmailDraftArgs
from secretary.tools.email import register as register_email
from secretary.tools.registry import Registry


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "c.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


def _deps():
    registry = Registry()
    register_email(registry)
    router = Router(registry)
    router.route("email_draft", ["email", "mail", "draft", "send"])
    router.route("email_send", ["email", "mail", "send"])
    return registry, router, Limiter(rpm=10000, tpm=100000, safety=1.0, clock=time.monotonic)


def _say(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=[], usage={}, headers={}, model="fake")


def _call(name: str, args: dict) -> LLMResponse:
    return LLMResponse(
        text="", tool_calls=[ToolCall(call_id="c1", name=name, args=args)],
        usage={}, headers={}, model="fake")


def _llm(*responses: LLMResponse) -> FakeLLM:
    fake = FakeLLM()
    for response in responses:
        fake.add(response)
    return fake


async def _run(conn, llm, text="send an email to a@b.com that says hi and no subject") -> str:
    registry, router, limiter = _deps()
    ctx = {"turn_id": "t1", "now": "2026-11-15T09:00:00+05:30", "tz": "Asia/Kolkata",
           "today_iso": "2026-11-15"}
    return await run_turn(text, ctx, llm, limiter, router, registry, conn)


def test_subject_is_optional_for_drafts():
    assert EmailDraftArgs(to="a@b.com", body="hi").subject == ""


@pytest.mark.asyncio
async def test_invented_draft_claim_is_retried_and_then_really_saved():
    conn = _conn()
    try:
        llm = _llm(
            _say("Draft saved (ID 29). It's in Approvals > Drafts."),  # claimed, no tool call
            _call("email_draft", {"to": "a@b.com", "body": "hi"}),     # after the nudge
            _say("Saved your draft in Approvals > Drafts."),
        )
        reply = await _run(conn, llm)
        assert len(messages_repo.list_drafts(conn)) == 1
        assert "Drafts" in reply
        sent = [str(m.get("content")) for m in llm.calls[-1]["messages"]]
        assert any("called no tool" in text for text in sent)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_persistent_invented_claim_is_replaced_with_honest_reply():
    conn = _conn()
    try:
        llm = _llm(
            _say("Draft saved (ID 29)."),
            _say("Done! The email has been sent."),
        )
        reply = await _run(conn, llm)
        assert messages_repo.list_drafts(conn) == []
        assert "haven't" in reply.lower() or "have not" in reply.lower()
        assert "ID 29" not in reply
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_questions_and_non_email_replies_are_untouched():
    conn = _conn()
    try:
        reply = await _run(conn, _llm(_say("Who should I send it to, and what should it say?")))
        assert reply == "Who should I send it to, and what should it say?"
        reply = await _run(conn, _llm(_say("Hello! How can I help?")), text="hi")
        assert reply == "Hello! How can I help?"
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_real_tool_call_then_claim_is_allowed():
    conn = _conn()
    try:
        llm = _llm(
            _call("email_draft", {"to": "a@b.com", "subject": "S", "body": "hi"}),
            _say("Draft saved. Find it in Approvals > Drafts."),
        )
        reply = await _run(conn, llm)
        assert reply == "Draft saved. Find it in Approvals > Drafts."
        assert len(llm.calls) == 2
    finally:
        conn.close()
