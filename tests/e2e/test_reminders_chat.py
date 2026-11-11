"""E2E: reminders from chat through the real composition root.

``remind me to drink water in 1 minute`` routes to ``reminder_create`` (class B),
which resolves the time in code and writes a scheduled reminder row. Chat echoes
a confirmation with the resolved time. Advancing the injected clock and running
the scheduler tick fires the reminder through a fake notifier into the inbox.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QApplication

from secretary.agent.router import Router
from secretary.app import WorkerThread
from secretary.controller import Controller
from secretary.llm.base import LLMResponse, ToolCall
from secretary.llm.fake import FakeLLM
from secretary.llm.limiter import Limiter
from secretary.scheduler.ticker import tick
from secretary.secrets import set_secret
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import inbox as inbox_repo
from secretary.store.repos import reminders as reminders_repo
from secretary.timeparse.when import resolve_when
from secretary.tools import registry as tools_registry
from secretary.tools import reminders as reminders_tools
from secretary.tools import tasks as tasks_tools

_NOW = datetime(2026, 11, 10, 9, 0, 0, tzinfo=UTC)
_TZ = "Asia/Kolkata"


class _FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []

    def notify(self, title: str, body: str, priority: bool = False) -> None:
        self.calls.append((title, body, priority))


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


def _conn(tmp_path) -> Connection:
    db = tmp_path / "rem.db"
    conn = Connection(db)
    migrate(conn._con, migrations_folder(), lambda: None)
    return conn


def _build_controller(conn, llm, submit_coro) -> Controller:
    registry = tools_registry.Registry()
    tasks_tools.register(registry)
    reminders_tools.register(registry)
    router = Router(registry)
    router.route("reminder_create", ["remind", "reminder"])
    router.route("reminder_list", ["remind", "reminder", "list", "show"])
    router.route("reminder_snooze", ["snooze", "reminder"])
    router.route("reminder_cancel", ["cancel", "reminder", "delete"])
    return Controller(
        conn,
        registry=registry,
        router=router,
        llm=llm,
        limiter=Limiter(rpm=60, tpm=6000, safety=0.7),
        submit_coro=submit_coro,
    )


class TurnSpy(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.replies: list[str] = []

    @Slot(str)
    def on_finished(self, text: str) -> None:
        self.replies.append(text)


def _wait_for_reply(controller, text, app, timeout=30.0):
    spy = TurnSpy()
    controller.turn_finished.connect(spy.on_finished)
    controller.send_message(text)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not spy.replies:
        app.processEvents()
        time.sleep(0.01)
    return spy.replies


def test_reminder_from_chat_fires_into_inbox(monkeypatch, tmp_path, worker_thread):
    set_secret("llm_api_key:groq", "fake-key")

    # Freeze the clock so "in 1 minute" resolves deterministically.
    monkeypatch.setattr(reminders_tools, "_utc_now", lambda: _NOW)

    fire_local = resolve_when("in 1 minute", _NOW, _TZ)
    fire_local_str = fire_local.strftime("%a %d %b, %I:%M %p %Z")

    llm = FakeLLM([
        LLMResponse(
            text="",
            tool_calls=[
                ToolCall(
                    call_id="c1",
                    name="reminder_create",
                    args={"title": "drink water", "when_text": "in 1 minute"},
                )
            ],
            usage={},
            headers={},
            model="fake",
        ),
        LLMResponse(
            text=f"Reminder set for {fire_local_str}",
            tool_calls=[],
            usage={},
            headers={},
            model="fake",
        ),
    ])

    app = QApplication.instance()
    conn = _conn(tmp_path)
    controller = _build_controller(conn, llm, worker_thread.submit)

    replies = _wait_for_reply(controller, "remind me to drink water in 1 minute", app)

    assert any(fire_local_str in r for r in replies), replies

    # The reminder row exists, scheduled at the code-resolved fire time.
    rows = reminders_repo.list_all(conn, status="scheduled")
    due = [r for r in rows if r["title"] == "drink water"]
    assert due, rows
    expected_fire_utc = (_NOW + timedelta(minutes=1)).isoformat()
    assert due[0]["next_fire_at"] == expected_fire_utc, due[0]

    # Advance the clock past the fire time and run the scheduler tick.
    monkeypatch.setattr(
        "secretary.scheduler.ticker.now_utc", lambda: _NOW + timedelta(minutes=2)
    )

    notifier = _FakeNotifier()
    fired: list[dict] = []

    def on_fired(entries):
        fired.extend(entries)
        for entry in entries:
            notifier.notify(entry["title"], entry["body"], priority=True)

    tick(conn, on_fired=on_fired)

    assert fired, "reminder did not fire on the scheduler tick"
    inbox = inbox_repo.list_unacknowledged(conn)
    assert any(r["title"] == "drink water" for r in inbox), inbox
    assert notifier.calls, "fake notifier was not invoked"
