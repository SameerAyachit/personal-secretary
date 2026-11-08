"""Command-line entry point (plan __main__.py).

Usage:
    python -m secretary            # normal windowed start
    python -m secretary --minimized   # start hidden to tray
    python -m secretary --diagnose    # print diagnostics and exit
"""

from __future__ import annotations

import argparse
import sys

from secretary.hotkey import GlobalHotkey, HotkeyFilter
from secretary.ui.quick_capture import QuickCapture

from .app import create_app
from .controller import Controller
from .diagnose import run_diagnose
from .logging_setup import setup_logging
from .paths import db_path
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
        window = MainWindow(controller)

        # Global hotkey for quick capture (Ctrl+Alt+Space).
        quick_capture = QuickCapture(controller)
        hotkey = GlobalHotkey(0x0003, 0x20, quick_capture.show_window)
        hotkey_filter = HotkeyFilter(hotkey, quick_capture.show_window)
        app.app.installNativeEventFilter(hotkey_filter)

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
