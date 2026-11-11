"""Heartbeat regression: the Qt main thread must never stall.

A QTimer on the main thread beats every 50 ms. During each scenario the largest
observed gap between consecutive beats must stay at or below 300 ms.

Scenario A -- slow 5 s FakeLLM chat turn through the real controller: agent
turns run on the worker loop (plan §3.1), never the GUI thread, so the
heartbeat keeps beating. On the pre-fix code (``asyncio.run`` per turn on the
GUI thread) the gap spiked to ~5 s.
Scenario B -- reminder firing through the real Notifier path with a desktop
backend whose ``send()`` blocks: ``Notifier._show_notification`` used to run
that blocking WinRT call on the GUI thread, freezing it; after the fix the
toast send is pumped onto a background thread.
Scenario C -- research_brief through the real controller: search, fetch and the
LLM calls run on the worker loop.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtWidgets import QApplication

from secretary.agent.router import Router
from secretary.app import WorkerThread
from secretary.controller import Controller
from secretary.llm.base import LLMResponse, ToolCall
from secretary.llm.limiter import Limiter
from secretary.notify.notifier import Notifier
from secretary.secrets import set_secret
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.tools import reminders as reminders_tools
from secretary.tools import research as research_tools
from secretary.tools import tasks as tasks_tools
from secretary.tools.registry import Registry

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class HeartbeatMonitor:
    """Stamps a beat from a QTimer living on the GUI thread."""

    def __init__(self, interval_ms: int = 50) -> None:
        self._timer = QTimer()
        self._timer.setInterval(interval_ms)
        self._beats: list[float] = []
        self._timer.timeout.connect(self._beat)  # type: ignore[arg-type]

    def start(self) -> None:
        self._beats = [time.monotonic()]
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _beat(self) -> None:
        self._beats.append(time.monotonic())

    def max_gap(self) -> float:
        if len(self._beats) < 2:
            return 0.0
        return max(b - a for a, b in zip(self._beats, self._beats[1:], strict=False))


class TurnSpy(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.replies: list[str] = []

    @Slot(str)
    def on_finished(self, text: str) -> None:
        self.replies.append(text)


class _SlowLLM:
    """LLM client that blocks the thread running the turn for ``delay`` seconds."""

    def __init__(self, delay: float, text: str = "slow turn reply") -> None:
        self.delay = delay
        self.text = text
        self.calls = 0

    async def chat(self, *, messages, tools, max_tokens, temperature, purpose, **kwargs):
        await asyncio.sleep(self.delay)
        self.calls += 1
        return LLMResponse(text=self.text, tool_calls=[], usage={}, headers={}, model="fake")

    async def list_models(self) -> list[str]:
        return ["fake"]


def _conn(tmp_path: Path) -> Connection:
    db = tmp_path / "hb.db"
    conn = Connection(db)
    migrate(conn._con, migrations_folder(), lambda: None)
    return conn


def _registry_router() -> tuple[Registry, Router]:
    registry = Registry()
    tasks_tools.register(registry)
    reminders_tools.register(registry)
    research_tools.register(registry)
    router = Router(registry)
    router.route("reminder_create", ["remind", "reminder"])
    router.route("research_brief", ["research", "brief", "summarize"])
    return registry, router


def _build_controller(conn, llm, submit_coro) -> Controller:
    registry, router = _registry_router()
    return Controller(
        conn,
        registry=registry,
        router=router,
        llm=llm,
        limiter=Limiter(rpm=60, tpm=6000, safety=0.7),
        submit_coro=submit_coro,
    )


def _pump_until(app: QApplication, condition, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not condition():
        app.processEvents()
        time.sleep(0.01)


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


def _wait_for_turn(controller, text, app, timeout=30.0):
    spy = TurnSpy()
    controller.turn_finished.connect(spy.on_finished)
    controller.send_message(text)
    _pump_until(app, lambda: bool(spy.replies), timeout)
    return spy


def test_main_thread_heartbeat_stays_under_300_ms(qapp, worker_thread, tmp_path):
    app = QApplication.instance()

    # Scenario A -- slow 5 s turn through the real controller (worker loop).
    monitor = HeartbeatMonitor()
    monitor.start()
    try:
        conn = _conn(tmp_path)
        set_secret("llm_api_key:groq", "fake-key")
        controller = _build_controller(conn, _SlowLLM(delay=5.0), worker_thread.submit)
        spy = _wait_for_turn(controller, "say ping", app)
        assert any("slow turn reply" in r for r in spy.replies), spy.replies
        gap = monitor.max_gap()
        assert gap <= 0.3, f"main thread stalled during slow turn: max gap {gap:.3f} s"
    finally:
        monitor.stop()

    # Scenario B -- reminder through the real Notifier with a blocking desktop
    # backend: the toast send must not freeze the GUI thread.
    monitor = HeartbeatMonitor()
    monitor.start()
    try:
        notifier = Notifier()
        notifier._desktop_sync = _BlockingDesktop(delay=1.5)  # type: ignore[assignment]
        notifier.notify("Reminder", "drink water", priority=True)
        app.processEvents()  # delivers _show_notification on the GUI thread
        gap = monitor.max_gap()
        assert gap <= 0.3, f"main thread blocked by notifier: max gap {gap:.3f} s"
    finally:
        monitor.stop()

    # Scenario C -- research_brief through the real controller (worker loop).
    monitor = HeartbeatMonitor()
    monitor.start()
    try:
        conn = _conn(tmp_path)
        set_secret("llm_api_key:groq", "fake-key")
        conn.search_provider = _FakeSearchProvider()
        # research_brief_tool reads conn.llm for its internal plan/summarize/write/check calls.
        conn.llm = _ScriptedLLM(
            [
                LLMResponse(
                    text=json.dumps({"queries": ["artificial general intelligence"]}),
                    tool_calls=[],
                    usage={},
                    headers={},
                    model="fake",
                ),
                LLMResponse(
                    text=json.dumps({"summary": "source summary", "claims": []}),
                    tool_calls=[],
                    usage={},
                    headers={},
                    model="fake",
                ),
                LLMResponse(
                    text=json.dumps({"brief": "Brief on AGI."}),
                    tool_calls=[],
                    usage={},
                    headers={},
                    model="fake",
                ),
                LLMResponse(
                    text=json.dumps({"keep": [0]}), tool_calls=[], usage={}, headers={}, model="fake"
                ),
            ]
        )
        research_tools.fetch_url = _fake_fetch_url  # type: ignore[assignment]
        turn_responses = [
            # run_turn iteration 1: the LLM calls the research_brief tool.
            LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        call_id="c1",
                        name="research_brief",
                        args={"topic": "artificial general intelligence", "depth": "standard"},
                    )
                ],
                usage={},
                headers={},
                model="fake",
            ),
            # run_turn iteration 2: final reply after the tool result.
            LLMResponse(text="Here is your brief: Brief on AGI.", tool_calls=[], usage={}, headers={}, model="fake"),
        ]
        turn_llm = _ScriptedLLM(turn_responses)
        controller = _build_controller(conn, turn_llm, worker_thread.submit)
        spy = _wait_for_turn(controller, "research brief on artificial general intelligence", app)
        assert any("Brief on AGI" in r for r in spy.replies), spy.replies
        gap = monitor.max_gap()
        assert gap <= 0.3, f"main thread stalled during research_brief: max gap {gap:.3f} s"
    finally:
        monitor.stop()


class _BlockingDesktop:
    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.calls = 0

    def send(self, title: str, message: str) -> None:
        self.calls += 1
        time.sleep(self.delay)


class _FakeSearchProvider:
    def search(self, query: str, n: int = 5) -> list[dict]:
        return [{"url": "https://example.com/source", "title": "Example source"}]


def _fake_fetch_url(url: str) -> dict:
    return {"text": "Example source text about artificial general intelligence."}


class _ScriptedLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def chat(self, *, messages, tools, max_tokens, temperature, purpose, **kwargs):
        self.calls += 1
        return self._responses.pop(0)

    async def list_models(self) -> list[str]:
        return ["fake"]
