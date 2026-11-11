"""UI tests for the research brief view (offscreen, plan §14 / §12).

The view runs research_brief on the worker loop and displays the sourced
brief with citations; the LLM and fetch are faked so no network is needed.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QApplication

import secretary.controller as controller_module
from secretary.agent.router import Router
from secretary.app import WorkerThread
from secretary.controller import Controller
from secretary.llm.base import LLMResponse
from secretary.llm.limiter import Limiter
from secretary.secrets import set_secret
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.tools import research as research_tools
from secretary.tools import tasks as tasks_tools
from secretary.tools.registry import Registry
from secretary.ui.views.research import ResearchView


class ResearchSpy(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[object] = []

    @Slot(object)
    def on_result(self, result: object) -> None:
        self.results.append(result)


class _ScriptedLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def chat(self, *, messages, tools, max_tokens, temperature, purpose, **kwargs):
        self.calls += 1
        return self._responses.pop(0)

    async def list_models(self) -> list[str]:
        return ["fake"]


class _FakeSearchProvider:
    def search(self, query: str, n: int = 5) -> list[dict]:
        return [{"url": "https://example.com/source", "title": "Example source"}]


def _fake_fetch_url(url: str) -> dict:
    return {"text": "Example source text about artificial general intelligence."}


def _conn(tmp_path: Path) -> Connection:
    db = tmp_path / "research.db"
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


def _build_controller(tmp_path: Path, worker_thread: WorkerThread, monkeypatch) -> Controller:
    conn = _conn(tmp_path)
    set_secret("llm_api_key:groq", "fake-key")
    conn.search_provider = _FakeSearchProvider()
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
                text=json.dumps({"keep": [0]}),
                tool_calls=[],
                usage={},
                headers={},
                model="fake",
            ),
        ]
    )
    monkeypatch.setattr(research_tools, "fetch_url", _fake_fetch_url)
    registry = Registry()
    tasks_tools.register(registry)
    research_tools.register(registry)
    router = Router(registry)
    router.route("research_brief", ["research", "brief", "summarize"])
    return Controller(
        conn,
        registry=registry,
        router=router,
        llm=None,
        limiter=Limiter(rpm=60, tpm=6000, safety=0.7),
        submit_coro=worker_thread.submit,
    )


def test_research_brief_shows_brief_and_sources(qapp, worker_thread, tmp_path, monkeypatch):
    app = QApplication.instance()
    controller = _build_controller(tmp_path, worker_thread, monkeypatch)
    view = ResearchView(controller)
    view._topic.setText("artificial general intelligence")
    spy = ResearchSpy()
    controller.research_brief_finished.connect(spy.on_result)
    view._run_btn.click()
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline and not spy.results:
        app.processEvents()
        time.sleep(0.01)
    assert spy.results, "no research brief result"
    result = spy.results[-1]
    assert not result.get("error"), result
    assert "Brief on AGI" in result.get("brief", "")
    assert "Brief on AGI" in view._brief.toPlainText()
    assert view._sources.count() >= 1
    assert "https://example.com/source" in view._sources.item(0).text()


def test_research_empty_topic_shows_error_without_worker(qapp, worker_thread, tmp_path, monkeypatch):
    controller = _build_controller(tmp_path, worker_thread, monkeypatch)
    view = ResearchView(controller)
    view._topic.setText("")
    view._run_btn.click()
    assert view._error.text() == "Enter a topic to research."
    assert view._brief.toPlainText() == ""


def test_research_failure_shows_error(qapp, worker_thread, tmp_path, monkeypatch):
    app = QApplication.instance()
    controller = _build_controller(tmp_path, worker_thread, monkeypatch)

    async def boom(conn, turn_id, args):
        raise RuntimeError("research pipeline down")

    monkeypatch.setattr(controller_module, "research_brief_tool", boom)
    view = ResearchView(controller)
    view._topic.setText("anything")
    spy = ResearchSpy()
    controller.research_brief_finished.connect(spy.on_result)
    view._run_btn.click()
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline and not spy.results:
        app.processEvents()
        time.sleep(0.01)
    assert spy.results, "no research brief result"
    result = spy.results[-1]
    assert "error" in result and "research pipeline down" in result["error"]
    assert view._error.text() == result["error"]
