"""Unit tests for the main-thread heartbeat watchdog (plan C-27)."""

from __future__ import annotations

import time
from unittest.mock import patch

from secretary.util.main_thread_watchdog import MainThreadWatchdog


def test_beat_updates_last_beat() -> None:
    wd = MainThreadWatchdog(stall_seconds=5.0)
    before = wd._last_beat
    time.sleep(0.02)
    wd.beat()
    assert wd._last_beat >= before


def test_tick_dumps_traceback_when_stalled(caplog) -> None:
    wd = MainThreadWatchdog(stall_seconds=5.0)
    wd._last_beat = time.monotonic() - 10.0  # simulate a stalled GUI thread
    with patch(
        "secretary.util.main_thread_watchdog.faulthandler.dump_traceback"
    ) as dumped:
        wd._tick()
        dumped.assert_called_once()
    assert "stalled" in caplog.text


def test_tick_silent_when_fresh() -> None:
    wd = MainThreadWatchdog(stall_seconds=5.0)
    wd.beat()
    with patch(
        "secretary.util.main_thread_watchdog.faulthandler.dump_traceback"
    ) as dumped:
        wd._tick()
        dumped.assert_not_called()


def test_start_stop() -> None:
    wd = MainThreadWatchdog(stall_seconds=5.0)
    wd.start()
    thread = wd._thread
    assert thread is not None and thread.is_alive()
    wd.stop()
    assert not thread.is_alive()
    # Idempotent.
    wd.stop()
