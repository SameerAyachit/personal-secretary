"""Regression tests for bugs found in the code review (all FAIL on the reviewed snapshot).

Put this file in tests/e2e/. It uses the project's own conftest (in-memory keyring,
temp data root) so it never touches real keys. Each test names the bug it guards.
Do not weaken a test to make it pass; fix the code.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import gc
import os
from datetime import UTC, datetime

import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from secretary.agent.loop import _execute_call
from secretary.controller import Controller
from secretary.llm.base import ToolCall
from secretary.notify.notifier import Notifier
from secretary.notify.popup import PopupCard
from secretary.scheduler.ticker import tick
from secretary.secrets import get_secret, set_secret
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.tools import reminders as rt
from secretary.tools.registry import Registry, SafetyClass, ToolSpec
from secretary.ui.views.settings import SettingsView
from secretary.ui.views.tasks import TasksView


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def conn(tmp_path):
    c = Connection(tmp_path / "t.db")
    migrate(c._con, migrations_folder(), lambda: None)
    yield c
    c.close()


def _sync_submit(coro):
    """Run a coroutine to completion and return a finished future (no worker needed)."""
    fut: concurrent.futures.Future = concurrent.futures.Future()
    try:
        fut.set_result(asyncio.run(coro))
    except Exception as exc:  # pragma: no cover
        fut.set_exception(exc)
    return fut


# BUG 1: send_message never increments the turn id, so every chat turn is "turn-0".
# reminders.idempotency_key is UNIQUE and derived from the turn id, so asking for the
# same reminder twice (or after an app restart) raises IntegrityError and kills the turn.
def test_each_chat_message_gets_a_unique_turn_id(qapp, conn, monkeypatch):
    seen: list[str] = []

    async def fake_run_turn(text, ctx, *a, **k):
        seen.append(ctx["turn_id"])
        return "ok"

    monkeypatch.setattr("secretary.controller.run_turn", fake_run_turn)
    set_secret("llm_api_key:groq", "gsk_" + "x" * 52)
    c = Controller(conn, llm=object(), limiter=object(), router=object(), registry=object(),
                   submit_coro=_sync_submit)
    c.send_message("remind me to drink water in 1 minute")
    c.send_message("remind me to drink water in 1 minute")
    assert len(seen) == 2 and seen[0] != seen[1]


def test_same_reminder_requested_twice_does_not_crash(conn):
    args = {"title": "drink water", "when_text": "in 1 minute"}
    rt.reminder_create(conn, "turn-0", args)
    conn.execute("UPDATE reminders SET status='done'")  # first one already fired
    result = rt.reminder_create(conn, "turn-0", args)  # must not raise IntegrityError
    assert "error" not in result


# BUG 2: a failing tool must come back to the LLM as an error result, not abort the turn.
def test_tool_exception_is_reported_not_raised(conn):
    def boom(conn, turn_id, args):
        raise RuntimeError("tool exploded")

    reg = Registry()
    reg.register(ToolSpec("boom", "core", SafetyClass.A, "x", None, boom))
    out = asyncio.run(_execute_call(ToolCall(call_id="1", name="boom", args={}), reg, conn, "t"))
    assert "error" in out


# BUG 3: Settings > AI "Save provider" and the first-run wizard call set_secret with 3 args.
def test_set_llm_provider_saves_the_key(conn):
    c = Controller(conn)
    key = "gsk_" + "k" * 52
    c.set_llm_provider("groq", key, "https://api.groq.com/openai/v1", "openai/gpt-oss-120b")
    assert get_secret("llm_api_key:groq") == key


def test_blank_key_field_does_not_erase_the_saved_key(conn):
    c = Controller(conn)
    set_secret("llm_api_key:groq", "gsk_" + "k" * 52)
    c.set_llm_provider("groq", "", "https://api.groq.com/openai/v1", "openai/gpt-oss-120b")
    assert get_secret("llm_api_key:groq") == "gsk_" + "k" * 52


# BUG 4: chat has no memory: ctx["history"] is never supplied, so "yes" means nothing.
def test_follow_up_message_receives_previous_exchange(qapp, conn, monkeypatch):
    ctxs: list[dict] = []

    async def fake_run_turn(text, ctx, *a, **k):
        ctxs.append(ctx)
        return "Shall I search for papers?" if len(ctxs) == 1 else "ok"

    monkeypatch.setattr("secretary.controller.run_turn", fake_run_turn)
    set_secret("llm_api_key:groq", "gsk_" + "x" * 52)
    c = Controller(conn, llm=object(), limiter=object(), router=object(), registry=object(),
                   submit_coro=_sync_submit)
    c.send_message("find papers on AQI prediction")
    c.send_message("yes")
    history = ctxs[1].get("history") or []
    assert any("papers" in str(m.get("content", "")) for m in history)


# BUG 5: the Settings view makes a blocking network call (asyncio.run on the Qt thread)
# while it is being constructed, i.e. at app start.
def test_settings_view_does_not_fetch_models_on_construction(qapp, conn, monkeypatch):
    calls = []
    monkeypatch.setattr(Controller, "get_available_models",
                        lambda self, provider=None: calls.append(provider) or [])
    SettingsView(Controller(conn))
    assert calls == []


# BUG 6: Tasks quick-add "remind me ..." creates a reminder with no fire time, so it never fires.
def test_quick_add_reminder_has_a_fire_time(qapp, conn):
    view = TasksView(Controller(conn))
    view._input.setText("remind me to drink water in 1 minute")
    view._on_add()
    rows = conn.execute("SELECT next_fire_at FROM reminders").fetchall()
    assert rows and all(r["next_fire_at"] for r in rows)


# BUG 7: snooze stores the text "10 minutes" as a timestamp; the ticker un-snoozes it at once.
def test_snooze_stores_a_real_future_timestamp_and_survives_a_tick(conn):
    conn.execute(
        "INSERT INTO inbox(kind,title,body,status,created_at) "
        "VALUES('reminder','x','','unacknowledged','2026-01-01T00:00:00Z')"
    )
    iid = conn.execute("SELECT max(id) FROM inbox").fetchone()[0]
    Controller(conn).snooze_inbox(iid, "10 minutes")
    until = conn.execute("SELECT snoozed_until FROM inbox WHERE id=?", (iid,)).fetchone()[0]
    assert datetime.fromisoformat(until.replace("Z", "+00:00")) > datetime.now(UTC)
    tick(conn)
    status = conn.execute("SELECT status FROM inbox WHERE id=?", (iid,)).fetchone()[0]
    assert status == "snoozed"


# BUG 8: the reminder popup is a local variable, so Python deletes it as soon as the slot returns.
def test_popup_stays_alive_after_notification(qapp):
    n = Notifier()
    n._desktop_sync = None
    n._show_popup("Reminder", "drink water")
    qapp.processEvents()
    gc.collect()
    qapp.processEvents()
    assert [w for w in qapp.topLevelWidgets() if isinstance(w, PopupCard)]
