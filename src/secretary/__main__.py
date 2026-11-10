"""Command-line entry point (plan __main__.py).

Usage:
    python -m secretary            # normal windowed start
    python -m secretary --minimized   # start hidden to tray
    python -m secretary --diagnose    # print diagnostics and exit
"""

from __future__ import annotations

import argparse
import ctypes
import signal
import sys
from ctypes import wintypes

from PySide6.QtCore import QMetaObject, Qt

from secretary.agent.router import Router
from secretary.app import create_app
from secretary.integrations.search.provider import CircuitBreaker, DDGSSearchProvider, SearchService
from secretary.llm.limiter import Limiter
from secretary.llm.openai_compat import OpenAICompatClient
from secretary.tools import email as email_tools
from secretary.tools import events as events_tools
from secretary.tools import planning as planning_tools
from secretary.tools import registry as tools_registry
from secretary.tools import reminders as reminders_tools
from secretary.tools import research as research_tools
from secretary.tools import tasks as tasks_tools
from secretary.ui.quick_capture import QuickCapture

from .config import load_config
from .controller import Controller, get_active_llm_key
from .diagnose import run_diagnose
from .hotkey import GlobalHotkey, HotkeyFilter
from .logging_setup import setup_logging
from .notify.notifier import Notifier
from .paths import db_path
from .scheduler.ticker import SchedulerThread
from .store.db import Connection, migrations_folder
from .store.migrate import migrate
from .ui.main_window import MainWindow

# Windows console control event: Ctrl+C. 0 is the value of CTRL_C_EVENT.
CTRL_C_EVENT = 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="secretary", description="Secretary personal assistant")
    parser.add_argument("--minimized", action="store_true", help="start hidden to the tray")
    parser.add_argument("--diagnose", action="store_true", help="run diagnostics and exit")
    return parser


def _install_quit_on_ctrl_c(app) -> None:
    """Quit the event loop on Ctrl+C so main()'s ``finally`` runs cleanup().

    ``signal.signal(SIGINT)`` is not delivered while Qt's ``exec()`` is blocked
    in the platform message loop (notably on Windows), so on Windows we handle
    the console control event directly and post a quit to the GUI thread.
    No secrets or credentials are touched here.
    """
    if sys.platform == "win32":

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
        def _handler(ctrl_type: int) -> bool:
            if ctrl_type == CTRL_C_EVENT:
                QMetaObject.invokeMethod(app.app, "quit", Qt.ConnectionType.QueuedConnection)
                return True
            return False

        # Keep the callback referenced so it is not garbage-collected.
        _install_quit_on_ctrl_c._callback = _handler  # type: ignore[attr-defined]
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_handler, True)
        return

    def _handler(signum: int, frame) -> None:
        app.app.quit()

    signal.signal(signal.SIGINT, _handler)


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

    _install_quit_on_ctrl_c(app)

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
        planning_tools.register(registry)
        reminders_tools.register(registry)
        research_tools.register(registry)
        router = Router(registry)
        router.route("tasks_add", ["task", "create", "add", "remind"])
        router.route("tasks_list", ["task", "list", "show", "remind"])
        router.route("reminder_create", ["remind", "reminder"])
        router.route("reminder_list", ["remind", "reminder", "list", "show"])
        router.route("reminder_snooze", ["snooze", "reminder"])
        router.route("reminder_cancel", ["cancel", "reminder", "delete"])
        router.route("email_send", ["send", "email"])
        router.route("web_search", ["search", "web"])
        router.route("event_create", ["event", "calendar", "meeting", "appointment"])
        router.route("event_list", ["events", "calendar", "schedule", "agenda"])
        router.route("plan_day", ["plan", "planning", "schedule", "free", "slot"])
        router.route("research_brief", ["research", "brief", "summarize"])

        # LLM provider, limiter.
        llm = None
        limiter = None
        key = get_active_llm_key()
        if key:
            cfg = load_config()
            provider = cfg.llm.active
            prov = cfg.llm.providers[provider]
            llm = OpenAICompatClient(base_url=prov.base_url, api_key=key, model=prov.primary_model)
            limiter = Limiter(rpm=60, tpm=6000, safety=0.7)
        controller = Controller(conn, registry=registry, router=router, llm=llm, limiter=limiter)
        conn.llm = llm  # research_brief uses it; None when no LLM key is configured
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
