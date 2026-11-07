"""Tests for the worker thread (owns its asyncio loop, plan §3.1)."""

import asyncio

import pytest

from secretary.app import WorkerThread


async def _coro(value: int) -> int:
    await asyncio.sleep(0.01)
    return value


@pytest.mark.asyncio
async def test_worker_thread_runs_coroutine():
    worker = WorkerThread()
    worker.start()
    try:
        # Wait for the loop to be ready.
        for _ in range(100):
            if worker.loop is not None and worker._loop_ready:
                break
            await asyncio.sleep(0.01)
        assert worker.loop is not None
        assert worker._loop_ready

        future = worker.submit(_coro(42))
        result = future.result(timeout=5)
        assert result == 42
    finally:
        worker.stop()
