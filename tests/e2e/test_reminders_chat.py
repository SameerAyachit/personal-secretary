"""E2E: reminders from chat through the real composition root.

``remind me to drink water in 1 minute`` routes to ``reminder_create`` (class B),
which resolves the time in code and writes a scheduled reminder row. Chat echoes
a confirmation with the resolved time. Advancing the injected clock and running
the scheduler tick fires the reminder through a fake notifier into the inbox.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from secretary.agent.router import Router
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


def _conn(tmp_path) -> Connection:
    db = tmp_path / "rem.db"
    conn = Connection(db)
    migrate(conn._con, migrations_folder(), lambda: None)
    return conn


def _build_controller(conn, llm) -> Controller:
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
    )


def test_reminder_from_chat_fires_into_inbox(monkeypatch, tmp_path):
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

    conn = _conn(tmp_path)
    controller = _build_controller(conn, llm)

    finished = []
    controller.turn_finished.connect(finished.append)

    controller.send_message("remind me to drink water in 1 minute")

    assert any(fire_local_str in f for f in finished), finished

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
