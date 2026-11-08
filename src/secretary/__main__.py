"""Command-line entry point (plan __main__.py).

Usage:
    python -m secretary            # normal windowed start
    python -m secretary --minimized   # start hidden to tray
    python -m secretary --diagnose    # print diagnostics and exit
"""

from __future__ import annotations

import argparse
import sys

import keyring

from secretary.agent.router import Router
from secretary.app import create_app
from secretary.integrations.search.provider import CircuitBreaker, DDGSSearchProvider, SearchService
from secretary.llm.limiter import Limiter
from secretary.llm.openai_compat import OpenAICompatClient
from secretary.tools import email as email_tools
from secretary.tools import events as events_tools
from secretary.tools import registry as tools_registry
from secretary.tools import tasks as tasks_tools
from secretary.ui.quick_capture import QuickCapture

from .controller import Controller
from .diagnose import run_diagnose
from .hotkey import GlobalHotkey, HotkeyFilter
from .logging_setup import setup_logging
from .notify.notifier import Notifier
from .paths import db_path
from .scheduler.ticker import SchedulerThread
from .store.db import Connection, migrations_folder
from .store.migrate import migrate
from .ui.main_window import MainWindow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="secretary", description="Secretary personal assistant")
    parser.add_argument("--minimized", action="store_true", help="start hidden to the tray")
    parser.add_argument("--diagnose", action="store_true", help="run diagnostics and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging()

    if args.diagnose:
        return run_diagnose()

    app = create_app(argv)
    if not app.is_primary():
        print("Secretary is already running.", file=sys.stderr)
        return 0

    app.start_worker()
    try:
        conn = Connection(db_path())
        migrate(conn._con, migrations_folder(), lambda: None)
        controller = Controller(conn)

        # Tool registry + router.
        registry = tools_registry.Registry()
        tasks_tools.register(registry)
        email_tools.register(registry)
        events_tools.register(registry)
        router = Router(registry)
        router.route("tasks_add", ["task", "create", "add", "remind"])
        router.route("tasks_list", ["task", "list", "show", "remind"])
        router.route("reminders_add", ["remind", "reminder"])
        router.route("email_send", ["send", "email"])
        router.route("web_search", ["search", "web"])
        router.route("event_create", ["event", "calendar", "meeting", "appointment"])
        router.route("event_list", ["events", "calendar", "schedule", "agenda"])

        # LLM provider, limiter.
        llm = None
        limiter = None
        key = keyring.get_password("secretary", "llm_api_key:groq")
        if key:
            llm = OpenAICompatClient(base_url="https://api.groq.com/openai/v1", api_key=key, model="llama-3.1-8b-instant")
            limiter = Limiter(rpm=60, tpm=6000, safety=0.7)
        controller = Controller(conn, registry=registry, router=router, llm=llm, limiter=limiter)
        window = MainWindow(controller)

        # Search provider + cache + breaker.
        provider = DDGSSearchProvider()
        breaker = CircuitBreaker(failures=3, open_minutes=10)
        search_service = SearchService(conn, provider, breaker)
        conn.search_provider = search_service

        # Notifier + tray for reminders.
        notifier = Notifier(window.tray_icon())

        # Global hotkey for quick capture (Ctrl+Alt+Space).
        quick_capture = QuickCapture(controller)
        hotkey = GlobalHotkey(0x0003, 0x20, quick_capture.show_window)
        hotkey_filter = HotkeyFilter(hotkey, quick_capture.show_window)
        app.app.installNativeEventFilter(hotkey_filter)

        # Scheduler thread fires reminders into the inbox.
        def on_fired(entries):
            for entry in entries:
                notifier.notify(entry["title"], entry["body"], priority=True)
            controller.inbox_changed.emit()

        scheduler = SchedulerThread(conn, on_fired=on_fired)
        scheduler.start()

        window.quick_capture = quick_capture
        if args.minimized:
            window.hide_to_tray()
        else:
            window.show()
        return app.run()
    finally:
        app.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
