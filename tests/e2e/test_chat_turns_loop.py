"""E2E: 10 consecutive chat turns through the real composition root with a real
OpenAI-compatible LLM client over respx-mocked HTTP.

Regression test for the "event loop is closed" bug: ``Controller.send_message``
used to run each turn with ``asyncio.run()``, which creates a brand-new event
loop per message. The shared ``httpx.AsyncClient`` (connection pool) is bound
to the loop of the first call, so the second call raised
``sqlite3.ProgrammingError`` / ``RuntimeError: Event loop is closed`` and no
reminder or reply was produced.

Fix: every agent turn runs on ONE persistent ``asyncio`` loop owned by the
worker thread (plan §3.1), submitted via ``run_coroutine_threadsafe``, with the
result delivered back to the UI through the ``turn_finished`` Qt signal.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
import pytest
import respx
from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QApplication

from secretary.agent.router import Router
from secretary.app import WorkerThread
from secretary.controller import Controller
from secretary.llm.limiter import Limiter
from secretary.llm.openai_compat import OpenAICompatClient
from secretary.secrets import set_secret
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.tools import events as events_tools
from secretary.tools import memory as memory_tools
from secretary.tools import planning as planning_tools
from secretary.tools import registry as tools_registry
from secretary.tools import reminders as reminders_tools
from secretary.tools import research as research_tools
from secretary.tools import tasks as tasks_tools

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE_URL = "http://127.0.0.1:19876"
CHAT_URL = f"{BASE_URL}/chat/completions"


class TurnSpy(QObject):
    """Collects ``turn_finished`` emissions on the GUI thread."""

    def __init__(self) -> None:
        super().__init__()
        self.replies: list[str] = []

    @Slot(str)
    def on_finished(self, text: str) -> None:
        self.replies.append(text)


def _conn(tmp_path: Path) -> Connection:
    db = tmp_path / "turns.db"
    conn = Connection(db)
    migrate(conn._con, migrations_folder(), lambda: None)
    return conn


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def worker_thread(qapp):
    worker = WorkerThread()
    worker.start()
    deadline = time.monotonic() + 5
    while worker.loop is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert worker.loop is not None, "worker loop did not start"
    yield worker
    worker.stop()


def _build_controller(conn, llm, submit_coro):
    registry = tools_registry.Registry()
    tasks_tools.register(registry)
    events_tools.register(registry)
    planning_tools.register(registry)
    reminders_tools.register(registry)
    memory_tools.register(registry)
    research_tools.register(registry)
    router = Router(registry)
    router.route("tasks_add", ["task", "create", "add", "remind"])
    router.route("tasks_list", ["task", "list", "show", "remind"])
    router.route("reminder_create", ["remind", "reminder"])
    router.route("reminder_list", ["remind", "reminder", "list", "show"])
    router.route("reminder_snooze", ["snooze", "reminder"])
    router.route("reminder_cancel", ["cancel", "reminder", "delete"])
    router.route("memory_remember", ["remember", "memory"])
    router.route("memory_forget", ["forget", "memory"])
    router.route("email_send", ["send", "email"])
    router.route("web_search", ["search", "web"])
    router.route("event_create", ["event", "calendar", "meeting", "appointment"])
    router.route("event_list", ["events", "calendar", "schedule", "agenda"])
    router.route("plan_day", ["plan", "planning", "schedule", "free", "slot"])
    router.route("research_brief", ["research", "brief", "summarize"])
    return Controller(
        conn,
        registry=registry,
        router=router,
        llm=llm,
        limiter=Limiter(rpm=60, tpm=6000, safety=0.7),
        submit_coro=submit_coro,
    )


def _chat_response(text: str, call_count: int) -> dict:
    return {
        "id": f"chatcmpl-{call_count}",
        "model": "test-model",
        "choices": [
            {
                "message": {"role": "assistant", "content": text, "tool_calls": []},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
    }


@respx.mock
def test_ten_consecutive_chat_turns(qapp, worker_thread, tmp_path):
    """Ten consecutive turns through the real composition root must all succeed.

    On the pre-fix code (``asyncio.run`` per message) the second call fails with
    ``RuntimeError: Event loop is closed`` because the shared httpx client's
    connection pool is bound to the first (now closed) loop.
    """
    call_count = 0

    def _respond(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=_chat_response(f"reply {call_count}", call_count))

    respx.post(CHAT_URL).mock(side_effect=_respond)

    conn = _conn(tmp_path)
    set_secret("llm_api_key:nvidia", "test-key")
    llm = OpenAICompatClient(base_url=BASE_URL, api_key="test-key", model="test-model")
    controller = _build_controller(conn, llm, worker_thread.submit)

    replies = []
    for i in range(10):
        spy = TurnSpy()
        controller.turn_finished.connect(spy.on_finished)
        controller.send_message(f"message {i + 1}")
        app = QApplication.instance()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and len(spy.replies) == 0:
            app.processEvents()
            time.sleep(0.01)
        assert len(spy.replies) == 1, f"turn {i + 1} did not produce a reply; replies={spy.replies}"
        reply = spy.replies[0]
        assert not reply.startswith("I hit an error:"), reply
        assert f"reply {i + 1}" in reply, reply
        replies.append(reply)
    assert len(replies) == 10
