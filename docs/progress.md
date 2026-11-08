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

P1-05 DONE: src/secretary/llm/limiter.py (token-bucket rpm+tpm, RequestTooLarge when est exceeds bucket, reconcile from usage/headers), src/secretary/llm/tokens.py (vendored cl100k_base via TIKTOKEN_CACHE_DIR, chars/3 fallback), plus .gitignore rule for the regenerated tiktoken cache artifact. Tests: tests/unit/llm/test_limiter.py + tests/unit/llm/test_tokens.py. ruff ✓, pytest ✓ (92 tests total), lint-imports ✓ (7 kept, 0 broken).

Next: P1-06 tool registry, routing, safety classes, idempotency, undo (plan §8).

P1-06 DONE: src/secretary/tools/registry.py (SafetyClass A/B/C, ToolSpec, Registry, LLM schemas with safety_class+group), src/secretary/tools/idempotency.py (sha256 idempotency key), src/secretary/agent/router.py (keyword selection, core group always available), src/secretary/tools/tasks.py (task_create Class B, task_list Class A with pydantic args), src/secretary/tools/email.py (email_send Class C → pending_actions waiting). Tests: tests/unit/tools/{test_registry,test_router,test_idempotency,test_tasks,test_email}. ruff ✓, pytest ✓ (106 tests total), lint-imports ✓ (7 kept, 0 broken).

Next: P1-07 agent loop with guards and normalize_response (plan §8.1).

P1-07 DONE: src/secretary/agent/loop.py (run_turn with MAX_STEPS=5 guard, token budget via limiter, identical-call dedupe, cross-step loop detection, timeout), src/secretary/agent/normalize_response.py (Appendix C cases: JSON in content, fenced JSON, args-as-string, unknown tools dropped, duplicates deduped, trailing prose, empty content). Tests: tests/unit/agent/{test_loop,test_normalize_response} (12 tests). ruff ✓, pytest ✓ (118 tests total), lint-imports ✓ (7 kept, 0 broken).

### Phase 1 gate (plan §21 / protocol §5) — all green
- ruff check . ✓ (All checks passed)
- python -m pytest -q ✓ (118 tests passed)
- lint-imports ✓ (7 kept, 0 broken)
- python -m secretary --diagnose ✓ (DIAGNOSE OK: Python, config, keyring, store WAL+foreign_keys, tzdata)
- Packaging smoke ✓ (P0-05: PyInstaller one-folder dist/secretary/secretary.exe builds and runs)
- Eval re-run vs FakeLLM ✓ (docs/eval_results/2026-11-07_fakellm_contract.md, 100%)
- ADRs current (ADR-001 D1-D15, ADR-002 UI toolkit), CHANGELOG.md added, progress.md current
- Self-review ✓ (layering via import-linter; class C → pending_actions; untrusted text tool-less; no absolute timestamps from LLM; redaction filter)

Next: P1-08 Controller facade + Chat and Tasks views with manual quick-add working without the LLM (pytest-qt). Then Phase 2 (reminders/inbox/native shell).

P1-08 DONE: src/secretary/ui/theme/tokens.py (design tokens, light/dark palettes), src/secretary/ui/theme/qss.py (QSS generated from tokens), src/secretary/ui/main_window.py (left rail + QStackedWidget, hide-to-tray C-3, theme applied), src/secretary/ui/views/{chat,tasks,today,settings}.py, src/secretary/controller/__init__.py (Controller facade with signals/slots: create_task_manual, send_message, ack/snooze_inbox, approve/reject_action, create_reminder_manual, list_tasks). TasksView manual quick-add works without the LLM and persists to the store. Tests: tests/ui/test_main_window.py (hide-on-close, rail switching, quick-add). ruff ✓, pytest ✓ (126 tests total), lint-imports ✓ (7 kept, 0 broken), diagnose ✓.

Next: Phase 2 (reminders/inbox/native shell: P2-01 scheduler, P2-02 inbox model/view, P2-03 notifier layers, ...).

P2-01 DONE: src/secretary/scheduler/ticker.py (SchedulerThread with 30s tick on its own QThread; atomic fire via claim status='firing', reminder_runs + inbox + next-occurrence advance; duplicate guard via UNIQUE(reminder_id, scheduled_for) + IntegrityError skip; repeat alerts, snooze expiry, sweeper all per-tick steps isolated so one failure never stops another). Tests: tests/scheduler/test_ticker.py (4 tests: fire creates inbox+marks done, duplicate prevented, recurring advances, tick runs). ruff ✓, pytest ✓ (134 tests total), lint-imports ✓ (7 kept, 0 broken), diagnose ✓.

P2-02 DONE: src/secretary/ui/views/inbox.py (Inbox view with per-item Ack/Snooze/Done buttons), controller gains list_inbox()/done_inbox(), store/inbox_repo.update fixed to bind the row id. Tests: tests/ui/test_inbox.py (refresh shows items, ack transitions away, done transitions away). ruff ✓, pytest ✓ (137 tests total), lint-imports ✓ (7 kept, 0 broken), diagnose ✓.

P2-03 DONE: src/secretary/notify/notifier.py (toast via desktop-notifier best-effort, QSystemTrayIcon.showMessage fallback, popup card, tray badge; all wrapped in try/except + logging so a notifier failure never crashes the app or loses the inbox row). Tests: tests/notifier/test_notifier.py (toast sent, desktop failure still shows popup, no desktop -> popup, tray badge). ruff ✓, pytest ✓ (145 tests total), lint-imports ✓ (7 kept, 0 broken), diagnose ✓.

P2-04 DONE: src/secretary/scheduler/catchup.py (catch_up() groups missed reminders into one "While you were away" inbox entry; recurring reminders advanced to next future occurrence; those older than 24 h logged as missed and skipped; sweeper run). Tests: tests/scheduler/test_catchup.py (20 missed -> 1 entry, recurring advances, no-due case). ruff ✓, pytest ✓ (148 tests total), lint-imports ✓ (7 kept, 0 broken), diagnose ✓.

P2-05 DONE: src/secretary/ui/views/today.py (Today view: unacknowledged reminders top with Snooze/Done, quick-add field, Plan my day, "While you were away" card), src/secretary/ui/views/approvals.py (Approvals view shell: waiting class-C actions with Approve/Reject), controller gains list_pending_actions(), sweeper runs each scheduler tick. Tests: tests/ui/test_inbox.py extended. ruff ✓, pytest ✓ (151 tests total), lint-imports ✓ (7 kept, 0 broken), diagnose ✓.

P2-06 DONE: src/secretary/hotkey.py (HotkeyFilter native event filter for WM_HOTKEY), src/secretary/ui/quick_capture.py (centered quick-capture input, Enter sends, Esc closes), src/secretary/__main__.py (wires global hotkey Ctrl+Alt+Space + quick capture). ruff ✓, pytest ✓ (153 tests total), lint-imports ✓ (7 kept, 0 broken), diagnose ✓.

Next: P2-07 First-run wizard with Test connection.

P2-07 DONE: src/secretary/ui/views/onboarding.py (first-run wizard: provider/key, Test connection via controller, timezone/start_minimized), controller gains set_llm_provider/test_llm_connection/save_general/get_config (controller owns keyring/config/llm access; ui never touches store/llm directly). ruff ✓, pytest ✓ (156 tests total), lint-imports ✓ (7 kept, 0 broken), diagnose ✓.

Next: P2-08 Autostart toggle (Run key) and --minimized (installer.iss already wires Run key; Settings toggle in Phase 5). Then P2-09 Installer v0.1, manual test script, release v0.1.0.

P2-08 DONE: --minimized flag works (wired in __main__), Run-key autostart written by installer.iss (HKCU Run key). Settings toggle UI comes in Phase 5 Settings view.

P2-09 DONE-HUMAN-GATED: packaging/secretary.spec + packaging/installer.iss exist; PyInstaller one-folder exe builds (verified in P0-05). Inno Setup (iscc) build + clean-profile install need a human on a clean profile.

Next: Phase 3 (Calendar and planning: Google calendar read sync, events repo/view, plan_day).

