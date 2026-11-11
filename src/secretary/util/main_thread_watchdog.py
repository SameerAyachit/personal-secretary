"""Main-thread heartbeat watchdog (plan C-27).

A QTimer on the GUI thread beats (calls :meth:`beat`) every 50 ms while the app
runs. A background watchdog thread watches the last-beat timestamp; if the GUI
thread has not beaten for ``stall_seconds`` (5 s) it logs
``faulthandler.dump_traceback()`` so the blocking call site is captured --
evidence for freezes such as the desktop-notifier WinRT toast call that used to
run on the GUI thread.

The watchdog never touches Qt and never blocks the GUI thread.
"""

from __future__ import annotations

import faulthandler
import logging
import threading
import time

logger = logging.getLogger(__name__)

STALL_SECONDS = 5.0
CHECK_INTERVAL_SECONDS = 0.5


class MainThreadWatchdog:
    """Background monitor of the GUI-thread heartbeat."""

    def __init__(self, stall_seconds: float = STALL_SECONDS) -> None:
        self._stall_seconds = stall_seconds
        self._last_beat = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def beat(self) -> None:
        """Mark the GUI thread as alive. Call from the GUI thread only."""
        self._last_beat = time.monotonic()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._monitor, name="secretary-watchdog", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            self._thread = None
            thread.join(timeout=2.0)

    def _tick(self) -> None:
        """One check: dump tracebacks if the GUI thread has stalled."""
        if time.monotonic() - self._last_beat > self._stall_seconds:
            logger.error(
                "main-thread watchdog: GUI thread stalled for > %s s; "
                "dumping thread tracebacks",
                self._stall_seconds,
            )
            faulthandler.dump_traceback()

    def _monitor(self) -> None:
        while not self._stop.wait(CHECK_INTERVAL_SECONDS):
            self._tick()
