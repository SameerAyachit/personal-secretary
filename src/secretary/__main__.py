"""Command-line entry point (plan __main__.py).

Usage:
    python -m secretary            # normal windowed start
    python -m secretary --minimized   # start hidden to tray
    python -m secretary --diagnose    # print diagnostics and exit
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import signal
import sys
from ctypes import wintypes

from PySide6.QtCore import QMetaObject, Qt
from PySide6.QtNetwork import QLocalSocket

from secretary.agent.wiring import build_registry_and_router
from secretary.app import create_app
from secretary.integrations.google.clients import build_clients
from secretary.integrations.search.provider import CircuitBreaker, DDGSSearchProvider, SearchService
from secretary.llm.factory import build_llm
from secretary.llm.metered import MeteredClient
from secretary.selftest import run_selftest
from secretary.ui.quick_capture import QuickCapture

from .config import load_config
from .controller import Controller, get_active_llm_key
from .diagnose import run_diagnose
from .errors import install_excepthooks, install_reporter
from .hotkey import DEFAULT_HOTKEY, GlobalHotkey, HotkeyFilter, parse_hotkey
from .logging_setup import setup_logging
from .notify.notifier import Notifier
from .paths import backups_dir, config_path, credentials_path, db_path, logs_dir
from .scheduler.catchup import catch_up
from .scheduler.ticker import SchedulerThread
from .store.backup import backup_if_due
from .store.db import Connection, migrations_folder
from .store.migrate import migrate
from .store.repos import research_briefs as briefs_repo
from .store.repos import settings as settings_repo
from .ui.main_window import MainWindow

logger = logging.getLogger(__name__)

# Windows console control event: Ctrl+C. 0 is the value of CTRL_C_EVENT.
CTRL_C_EVENT = 0
_SOCKET_NAME = "SecretaryApp.SingleInstance"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="secretary", description="Secretary personal assistant")
    parser.add_argument("--minimized", action="store_true", help="start hidden to the tray")
    parser.add_argument("--diagnose", action="store_true", help="run diagnostics and exit")
    parser.add_argument("--selftest", metavar="NAME", help="run a real-machine selftest (chat|reminder|google|google-live|notify|all)")
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

    setup_logging(log_file=str(logs_dir() / "secretary.log"))
    install_excepthooks()

    if args.diagnose:
        return run_diagnose()

    if args.selftest:
        return run_selftest(args.selftest)

    app = create_app(argv)
    if not app.is_primary():
        # Second launch: connect to the existing instance's socket so its
        # newConnection signal fires and raises its window, then exit.
        socket = QLocalSocket()
        socket.connectToServer(_SOCKET_NAME)
        socket.waitForConnected(1000)
        return 0

    _install_quit_on_ctrl_c(app)

    app.start_worker()
    app.watchdog.start()
    conn = None
    scheduler = None
    try:
        conn = Connection(db_path())
        migrate(conn._con, migrations_folder(), lambda: None)
        # Tool registry + router (plan A7).
        registry, router = build_registry_and_router()

        # LLM provider + limiter (single factory shared with Controller.rebuild_llm).
        cfg = load_config()
        key = get_active_llm_key()
        llm, limiter = build_llm(cfg, key)
        prov = cfg.llm.providers[cfg.llm.active]
        logger.info(
            "llm config: path=%s provider=%s model=%r configured=%s",
            config_path(), cfg.llm.active, prov.primary_model, llm is not None,
        )
        if key and llm is None:
            logger.warning("LLM model not configured; open Settings > AI and pick a model")
        controller = Controller(
            conn,
            registry=registry,
            router=router,
            llm=llm,
            limiter=limiter,
            submit_coro=app.worker.submit,
        )
        controller.set_worker(app.worker)
        install_reporter(controller.error.emit)
        # Research uses conn.llm; metered so it shares the chat rate-limit budget (None = no usable model).
        conn.llm = MeteredClient(llm, limiter) if llm is not None else None
        conn.write(briefs_repo.fail_stale_running)  # jobs a closed app left 'running' can never finish
        window = MainWindow(controller, watchdog=app.watchdog)

        # Second-instance activation: raise this window.
        app.on_another_instance_activated(window.show_window)

        # Search provider + cache + breaker.
        provider = DDGSSearchProvider()
        breaker = CircuitBreaker(
            failures=cfg.search.breaker_failures, open_minutes=cfg.search.breaker_open_minutes
        )
        search_service = SearchService(conn, provider, breaker, cfg.search.cache_hours)
        conn.search_provider = search_service

        # Notifier + tray for reminders.
        # MainWindow owns the single tray icon; reuse it for notifications.
        notifier = Notifier(window.tray_icon())

        def on_popup_action(kind: str, inbox_id: int) -> None:
            if kind == "done":
                controller.ack_inbox(inbox_id)
            else:
                controller.snooze_inbox(inbox_id, "10 minutes")

        notifier.action_handler = on_popup_action

        # Global hotkey for quick capture (app.hotkey, default Ctrl+Alt+Space).
        quick_capture = QuickCapture(controller)
        try:
            hotkey_mods, hotkey_vk = parse_hotkey(cfg.app.hotkey)
        except ValueError:
            logger.warning("invalid app.hotkey %r; using %s", cfg.app.hotkey, DEFAULT_HOTKEY)
            hotkey_mods, hotkey_vk = parse_hotkey(DEFAULT_HOTKEY)
        hotkey = GlobalHotkey(hotkey_mods, hotkey_vk, quick_capture.show_window)
        hotkey_filter = HotkeyFilter(hotkey)
        app.app.installNativeEventFilter(hotkey_filter)

        # Scheduler thread fires reminders into the inbox.
        def on_fired(entries):
            for entry in entries:
                notifier.notify(entry["title"], entry["body"], priority=True, inbox_id=entry.get("inbox_id"))
            controller.inbox_changed.emit()

        # Google clients (plan §13): real credentials are human-gated, so
        # clients are None until Google is connected. The Gmail client is
        # rebuilt when the user connects (Controller.rebuild_google_client).
        gmail_client, calendar_client = build_clients(credentials_path())
        # Reminders that came due while the app was closed: one "While you were
        # away" inbox entry, before the scheduler starts firing (plan §10.4).
        try:
            away = conn.write(lambda con: catch_up(con, cfg.app.timezone or "UTC"))
            if away["count"]:
                notifier.notify("While you were away", f"{away['count']} reminder(s)", priority=True)
        except Exception:
            logger.exception("startup catch-up failed")
        try:
            backup_if_due(
                conn,
                backups_dir(),
                cfg.backup.keep,
                cfg.backup.min_hours_between,
                lambda k: settings_repo.get(conn, k),
                lambda k, v: settings_repo.set(conn, k, v, turn_id="backup"),
            )
        except Exception:
            logger.exception("startup backup failed")
        scheduler = SchedulerThread(
            conn,
            on_fired=on_fired,
            gmail_client=gmail_client,
            calendar_client=calendar_client,
            notifier=notifier,
            on_events_changed=controller.events_changed.emit,
            update_checker=controller.make_update_checker(),
            on_update_found=controller.update_found.emit,
        )
        scheduler.start()
        controller.set_scheduler(scheduler)
        controller.set_gmail_client(gmail_client)

        window.quick_capture = quick_capture
        if args.minimized:
            window.hide_to_tray()
        else:
            window.show()
        return app.run()
    finally:
        if scheduler is not None:
            scheduler.stop()
        if conn is not None:
            conn.close()
        app.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
