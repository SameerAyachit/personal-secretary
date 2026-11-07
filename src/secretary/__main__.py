"""Command-line entry point (plan __main__.py).

Usage:
    python -m secretary            # normal windowed start
    python -m secretary --minimized   # start hidden to tray
    python -m secretary --diagnose    # print diagnostics and exit
"""

from __future__ import annotations

import argparse
import sys

from .app import create_app
from .diagnose import run_diagnose
from .logging_setup import setup_logging
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
        window = MainWindow(app)
        if args.minimized:
            window.hide_to_tray()
        else:
            window.show()
        return app.run()
    finally:
        app.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
