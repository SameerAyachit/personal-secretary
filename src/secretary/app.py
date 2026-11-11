"""Application bootstrap: QApplication, single instance, worker thread (plan §3.1).

The agent worker owns its own ``asyncio`` loop in its own thread. The UI thread
never blocks; coroutines are submitted with ``asyncio.run_coroutine_threadsafe``.
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

from PySide6.QtCore import QThread
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QApplication

from secretary.util.main_thread_watchdog import MainThreadWatchdog

_SOCKET_NAME = "SecretaryApp.SingleInstance"


class WorkerThread(QThread):
    """A thread that runs an ``asyncio`` event loop for background agent work."""

    def __init__(self) -> None:
        super().__init__()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = False

    def run(self) -> None:  # type: ignore[override]
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop_ready = True
        self._loop.run_forever()
        self._loop.close()
        self._loop = None
        self._loop_ready = False

    def submit(self, coro) -> asyncio.Future:
        """Schedule a coroutine on the worker loop (thread-safe)."""
        if self._loop is None or not self._loop_ready:
            raise RuntimeError("worker loop is not running")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self.wait()


class App:
    """Holds the QApplication, the single-instance lock, and the worker thread."""

    def __init__(self, argv: list[str]) -> None:
        # Reuse an existing QApplication (tests may already have created one);
        # a standalone ``python -m secretary`` run creates a fresh one.
        self.app = QApplication.instance() or QApplication(argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setApplicationName("Secretary")
        self.app.setApplicationDisplayName("Secretary")

        self.worker = WorkerThread()
        self.server: QLocalServer | None = None
        self._is_primary = self._acquire_single_instance()
        self.watchdog = MainThreadWatchdog()

    def _acquire_single_instance(self) -> bool:
        """Return True if this process owns the single-instance lock."""
        self.server = QLocalServer()
        # Remove any stale socket from a crashed previous instance.
        QLocalServer.removeServer(_SOCKET_NAME)
        if self.server.listen(_SOCKET_NAME):
            return True
        # Another instance holds the lock.
        self.server = None
        return False

    def is_primary(self) -> bool:
        return self._is_primary

    def start_worker(self) -> None:
        self.worker.start()

    def stop_worker(self) -> None:
        self.worker.stop()

    def run(self) -> int:
        return self.app.exec()

    def on_another_instance_activated(self, handler: Callable[[], None]) -> None:
        """Register a handler invoked when a second instance tries to start."""
        if self.server is not None:
            self.server.newConnection.connect(handler)  # type: ignore[arg-type]

    def cleanup(self) -> None:
        self.stop_worker()
        self.watchdog.stop()
        if self.server is not None:
            self.server.close()
            QLocalServer.removeServer(_SOCKET_NAME)


def create_app(argv: list[str] | None = None) -> App:
    if argv is None:
        argv = list(sys.argv)
    return App(argv)
