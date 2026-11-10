"""Global exception hooks that log and surface errors to the UI.

Installs ``sys.excepthook`` (main thread) and ``threading.excepthook``
(worker threads). Every unhandled exception is logged through the secretary
logger (redacted, no secrets) and handed to an optional reporter callback so
the UI can show it as a visible error instead of being silently swallowed.
"""

from __future__ import annotations

import logging
import sys
import threading
import traceback
from collections.abc import Callable

logger = logging.getLogger("secretary")

_state: dict[str, Callable[[str, str], None] | None] = {"reporter": None}


def install_reporter(reporter: Callable[[str, str], None]) -> None:
    """Register a callback ``reporter(action, message)`` for UI error display."""
    _state["reporter"] = reporter


def _report(exc_type: type[BaseException], exc_value: BaseException,
            exc_tb, thread_name: str) -> None:
    """Log the exception and hand it to the UI reporter (if any)."""
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.exception("unhandled exception in %s:\n%s", thread_name, tb_text)
    reporter = _state["reporter"]
    if reporter is not None:
        try:
            reporter("exception", f"{exc_type.__name__}: {exc_value}")
        except Exception:  # never let the reporter crash the app
            logger.exception("error reporter failed")


def install_excepthooks() -> None:
    """Install excepthooks that log unhandled exceptions and report them to
    the UI reporter once one is registered."""

    def _main_hook(exc_type, exc_value, exc_tb):
        _report(exc_type, exc_value, exc_tb, "main-thread")

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        name = args.thread.name if args.thread is not None else "worker-thread"
        _report(args.exc_type, args.exc_value, args.exc_traceback, name)

    sys.excepthook = _main_hook
    threading.excepthook = _thread_hook
