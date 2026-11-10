"""Shutdown smoke test: start and stop the REAL composition root 20 times in a
row without a native abort (plan §C-3, §10.1, PART 4 stabilization).

Each iteration builds the full root used by ``python -m secretary`` (QApplication,
worker thread, store connection, Controller, registry + router, MainWindow and
SchedulerThread), runs one scheduler tick, then stops the scheduler thread,
closes the DB and runs ``app.cleanup()`` deterministically.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from secretary.agent.router import Router
from secretary.app import create_app
from secretary.controller import Controller
from secretary.paths import db_path
from secretary.scheduler.ticker import SchedulerThread
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.tools import email as email_tools
from secretary.tools import events as events_tools
from secretary.tools import memory as memory_tools
from secretary.tools import planning as planning_tools
from secretary.tools import reminders as reminders_tools
from secretary.tools import research as research_tools
from secretary.tools import tasks as tasks_tools
from secretary.tools.registry import Registry
from secretary.ui.main_window import MainWindow


def _build_root() -> tuple:
    app = create_app([])
    assert app.is_primary()
    app.start_worker()
    conn = Connection(db_path())
    migrate(conn._con, migrations_folder(), lambda: None)

    registry = Registry()
    tasks_tools.register(registry)
    email_tools.register(registry)
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

    controller = Controller(conn, registry=registry, router=router, llm=None, limiter=None)
    window = MainWindow(controller)
    scheduler = SchedulerThread(conn, on_fired=lambda entries: None)
    scheduler.start()
    return app, conn, scheduler, window


def test_composition_root_start_stop_20x():
    for _ in range(20):
        app, conn, scheduler, _window = _build_root()
        try:
            scheduler.stop()
        finally:
            conn.close()
            app.cleanup()
