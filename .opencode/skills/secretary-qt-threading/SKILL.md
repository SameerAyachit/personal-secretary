---
name: secretary-qt-threading
description: Use when writing or touching Qt code. Covers main-thread rules, controller signals, the worker pattern, and the pytest-qt recipe.
---
1. All Qt widget mutation happens on the main thread. Worker/scheduler code never calls widget methods directly; it emits controller signals.
2. The agent worker owns its own `asyncio` loop in its own thread; submit coroutines with `run_coroutine_threadsafe`; never `asyncio.run()` on the main thread.
3. `QApplication.setQuitOnLastWindowClosed(False)`; tray Quit is the only exit (reminders keep firing).
4. pytest-qt runs with `QT_QPA_PLATFORM=offscreen`. Use `qtbot` for widget tests; assert signals with `qtbot.waitSignal`.
5. Never block the main thread; slow work is a job with progress and cancel.
6. Run `pytest -q tests/ui` with `QT_QPA_PLATFORM=offscreen`.
