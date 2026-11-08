# Build progress

## Pre-flight (protocol §2b) — recorded
- OS: Windows-11-10.0.26200-SP0 (Windows target confirmed)
- Python: 3.12.10 (matches plan pin) — running inside `.venv`
- git: 2.55.0.windows.3 (init done)
- Context7: available; library ID `/websites/doc_qt_io_qtforpython-6` (PySide6 docs)
- Plan: 1498 lines confirmed at root
- `.venv` created in root; runtime + test + quality deps installed (PySide6, httpx, dateparser, python-dateutil, tzdata, tiktoken, keyring, desktop-notifier, pydantic, ddgs, trafilatura, pytest, pytest-qt, pytest-asyncio, respx, time-machine, hypothesis, ruff, mypy, import-linter, pre-commit)
- QT_QPA_PLATFORM=offscreen to be set in pytest config (pyproject.toml)

## Phase 0 (plan §19) — in progress
P0-01 skeleton: AGENTS.md ✓, 5 skills ✓, 6 commands ✓, 3 agents ✓, opencode.json ✓, ADR-001 ✓, docs/deps.md ✓, docs/human_todo.md ✓, docs/blockers.md ✓, docs/decisions_log.md ✓, `.opencode/skills/secretary-ui-design/SKILL.md` kept ✓ (human-supplied, untouched). src/secretary package stubs + .github/workflows/ci.yml + importlinter.toml.
P0-01 acceptance (ruff, pytest, lint-imports on empty package): ruff ✓, pytest ✓, lint-imports ✓ (7 kept, 0 broken). DONE — committed.

P0-02 LLM probe + provider decision: built llm/base.py, llm/errors.py, llm/openai_compat.py, llm/fake.py, llm/probe.py. Tests (9) pass, ruff green, lint-imports green. Live probe run needs a real Groq key → DONE-HUMAN-GATED (see docs/human_todo.md P0-02). Probe writes docs/groq_limits_<date>.md; ADR to be recorded by human after probe.

Next: P0-03 eval harness (FakeLLM contract — this part is runnable by agent; live run human-gated).

P0-03 eval harness + 40 cases + FakeLLM contract: tests/eval/{__init__,cases,harness,test_contract}. Report generated at docs/eval_results/2026-11-07_fakellm_contract.md (100% pass). ruff ✓, pytest ✓, lint-imports ✓. Live run against a real model needs a key → DONE-HUMAN-GATED (docs/human_todo.md P0-03/P1-09).

Next: P0-04 Qt shell spike (tray, window hide/show, single-instance, worker+asyncio, hotkey, popup card) — UI task, follows secretary-ui-design skill.

P0-04 Qt shell spike DONE: src/secretary/app.py (QApplication, setQuitOnLastWindowClosed=False, single-instance QLocalServer, WorkerThread with asyncio loop), src/secretary/__main__.py (--minimized/--diagnose), src/secretary/ui/main_window.py (hide-on-close per C-3), src/secretary/notify/tray.py, src/secretary/notify/popup.py (frameless always-on-top bottom-right), src/secretary/hotkey.py (win32 RegisterHotKey behind import guard), src/secretary/logging_setup.py (JSON-lines + redaction), src/secretary/diagnose.py. Tests (worker thread, main window, popup) pass offscreen. ruff ✓, pytest ✓, lint-imports ✓.
Pitfalls: QSystemTrayIcon in QtWidgets, QAction in QtGui, QLocalServer in QtNetwork (PySide6 6.12); win32 via importlib guard; closeEvent ignores+hides (C-3); WorkerThread.stop uses call_soon_threadsafe(loop.stop) then wait().

P0-05 packaging smoke DONE-HUMAN-GATED: packaging/secretary.spec (PyInstaller one-folder, tzdata + vendored cl100k_base + migrations + theme data), packaging/version_info.txt, packaging/installer.iss (HKCU Run key autostart per Appendix E). `pyinstaller packaging/secretary.spec` builds dist/secretary/secretary.exe (55 MB) and it runs --diagnose without crashing. Clean-profile install, toast from packaged exe with AUMID shortcut, Run-key autostart, full --diagnose pass need a human on a clean profile → DONE-HUMAN-GATED (docs/human_todo.md P0-05).

P0-06 Google OAuth HUMAN-GATED (real Google Cloud project + credentials.json needed).
P0-07 Credential Manager in packaged exe HUMAN-GATED.
P0-08 UI toolkit ADR DONE (docs/adr/ADR-002.md — Qt Widgets confirmed; P0-04 shell is the prototype).

Next: Phase 1 core (P1-01 paths/config/secrets/logging; P1-02 store; P1-03 timeparse; ...).

P1-01 DONE: src/secretary/paths.py (data_root via SECRETARY_DATA_ROOT, LOCALAPPDATA fallback), src/secretary/config.py (pydantic Config model + load_config merging config.toml with Appendix A defaults), src/secretary/secrets.py (keyring get/set/delete), src/secretary/logging_setup.py (JSON-lines + redaction, done earlier). Tests: tests/unit/config/{test_paths,test_config}, tests/unit/secrets/test_secrets (8 tests). ruff ✓, pytest ✓, lint-imports ✓.

P1-02 DONE: src/secretary/store/migrate.py (forward-only runner with schema_migrations tracking, exact plan §5.2 code), migrations/001_core..004_fts.sql (tasks, reminders, reminder_runs, events, facts, settings, inbox, pending_actions, action_log, conversations, messages, llm_usage, search_cache, search_idx FTS5 + triggers), src/secretary/store/db.py (Connection with WAL pragmas + RLock writer, FTS5 startup check), src/secretary/store/backup.py (online backup API, backup_if_due, prune, restore), src/secretary/store/repos/ (tasks, reminders, inbox, pending_actions, action_log, events, facts, conversations, llm_usage, settings, _base). Tests: tests/unit/store/{test_migrate,test_backup} (5 tests). Fixes: migrations_folder() now points to repo-root migrations/; backup() returns dst. ruff ✓ (26 tests total), pytest ✓, lint-imports ✓ (7 kept, 0 broken). Committed.

P1-03 DONE: src/secretary/timeparse/when.py (resolve_when with dateparser, DMY order, RELATIVE_BASE, AmbiguousTime/PastTime, whole-phrase synonyms tonight→20:00/EOD→20:00, half-hour→30 minutes), src/secretary/timeparse/format.py (format_when echo with weekday/date/time/zone). Tests: tests/unit/timeparse/test_when.py (14 tests) covering day-first, past-time, relative, synonyms, tz-aware output, unparseable. ruff ✓, pytest ✓ (40 tests total), lint-imports ✓.

P1-04 DONE: src/secretary/timeparse/recurrence.py (grammar parser parse_recurrence → RecurrenceRule; next_occurrence via dateutil.rrule/wall-clock + month-end clamp to last day of shorter months; UnparseableRecurrence). Tests: tests/unit/timeparse/test_recurrence.py (16 unit + hypothesis property tests: daily always-after, weekdays-is-weekday). ruff ✓, pytest ✓ (64 tests total), lint-imports ✓ (7 kept, 0 broken).

Next: P1-05 LLM limiter + tokens (vendored cl100k_base encoding, TIKTOKEN_CACHE_DIR, RequestTooLarge, token-bucket reconcile). LLM client/FakeLLM/errors already built in P0-02.

