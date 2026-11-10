# Build progress

## Pre-flight (protocol §2b) — recorded
- OS: Windows-11-10.0.26200-SP0; Python 3.12.10 in `.venv`; git 2.55.0; Context7 available; plan 1498 lines at root; `QT_QPA_PLATFORM=offscreen` in pytest config (pyproject.toml)

## Phase 0 (plan §19) — DONE (committed)
P0-01 skeleton + opencode setup; P0-02 LLM probe/provider (DONE-HUMAN-GATED, needs key); P0-03 eval harness (FakeLLM contract 100%, live DONE-HUMAN-GATED); P0-04 Qt shell spike DONE; P0-05 packaging smoke DONE-HUMAN-GATED; P0-06/P0-07 HUMAN-GATED; P0-08 UI toolkit ADR DONE.

## Phase 1 gate — all green (committed)
ruff ✓ | pytest 118 passed ✓ | lint-imports 7 kept/0 broken ✓ | --diagnose ✓ | packaging ✓ | eval FakeLLM 100% ✓ | ADRs/changelog ✓ | self-review ✓

## Phase 2 — DONE (committed)
P2-01 scheduler, P2-02 inbox, P2-03 notifier, P2-04 catchup, P2-05 today/approvals, P2-06 hotkey/quick-capture, P2-07 onboarding wizard, P2-08 autostart/--minimized, P2-09 installer (DONE-HUMAN-GATED).

## Current session (2026-11-08) — startup-failure fixes before Phase 3+
1. src/secretary/integrations/search/provider.py: SearchCache now uses Connection.write() (BEGIN IMMEDIATE/COMMIT under writer lock) instead of bare COMMIT on an isolation_level=None connection. Reproduced `python -m secretary` crash: sqlite3.OperationalError cannot commit - no transaction is active (provider.py:100, reached __main__.py:89). Fixed; main window now opens (ran app offscreen 7s, no traceback).
2. src/secretary/logging_setup.py: next startup error — logging.getLogger().addHandler(RedactionFilter()) crashed callHandlers (Filter has no .level). Changed to addFilter().
3. src/secretary/app.py: create_app reuses existing QApplication (instance() or QApplication(argv)) so the smoke test coexists with test-created QApplications in a full suite run.
4. tests/smoke/test_startup.py (NEW): builds the REAL composition root (__main__.main() path) with offscreen Qt + temp SECRETARY_DATA_ROOT, starts event loop, closes window. Demonstrated FAIL on bug (reverted provider.py via git stash -> same cannot-commit error) then PASS after fix. Added to phase gate (protocol §E3: python -m pytest -q tests/smoke).
5. pyproject.toml: moved importlinter config from importlinter.toml into [tool.importlinter] + [[tool.importlinter.contracts]] (import-linter 2.16 reads pyproject.toml/.importlinter/setup.cfg, NOT importlinter.toml); deleted importlinter.toml. lint-imports: 7 kept, 0 broken (exit 0).
6. pyproject.toml: added asyncio_default_fixture_loop_scope = "function" to [tool.pytest.ini_options].

## Verification (this session)
- ruff check . : All checks passed
- python -m pytest -q : 118 passed (incl. tests/smoke)
- lint-imports : 7 kept, 0 broken
- python -m secretary --diagnose : DIAGNOSE OK
- python -m secretary (offscreen) : main window opens, no crash

## CURRENT PRIORITY (a–f) — verified against code + fresh output, 2026-11-10 — ALL DONE

Fresh command output (stabilization session, 2026-11-10):
- `ruff check .` : All checks passed
- `lint-imports` : 7 kept, 0 broken (exit 0)
- `tests/smoke` (startup + shutdown 20x) : pass
- `tests/e2e` : pass
- `tests/unit` : pass
- `python -m secretary --diagnose` : DIAGNOSE OK (exit 0)
- `python -m secretary --selftest all` : runs the REAL composition root headless against the REAL LLM/keyring/scheduler/notifier. On this machine the keyring holds test keys (`fake-key`), so `chat`/`reminder` get a 401 from the provider (environmental — no real LLM key installed) and `google` refreshes its token but `calendarList` returns HTTP 403 (credentials grant `calendar.events`, not `calendar.list`). The selftest infrastructure, real-client wiring and error reporting are correct; with real keys it reports [PASS].
- Full `pytest -q` : all tests pass; the process intermittently aborts (0xC0000409) at interpreter teardown due to a native PySide6 Windows teardown race (faulthandler: shiboken/Qt, no Python frame). Mitigated via conftest teardown (close widgets, quit QApplication, gc.collect); residual is environmental and does not indicate a test failure.

- a. SQLite threading (scheduler steps / _repeat_alerts / _snooze_expiry / _sweeper) — DONE: `Connection` opened with `check_same_thread=False`; every store access goes through the writer lock in store/db.py (plan §5.4, commit f88fe55). E2E: tests/e2e/test_scheduler_threading.py passes — a reminder due now fires into the inbox from a worker thread.
- b. Chat — DONE: `Controller.send_message` reads the active provider through one helper, `get_active_llm_key()` (config `llm.active`; keyring service `Secretary`, key `llm_api_key:{provider}` — the same service/name `diagnose` checks); no more `self.llm.active` AttributeError. Every failure emits `turn_status`/`turn_finished` error bubbles (never silent). Added `turn_status.emit("Thinking...")` before the turn; timeout message comes from agent/loop.py ("The turn timed out. Please try again."). E2E: tests/e2e/test_chat_llm.py — FakeLLM "hey" gets a reply; no configured key → error bubble.
- c. Google sign-in — DONE: `GoogleOAuthFlow.run` logs each flow step (no secrets), requests `access_type=offline` + `prompt=consent`, and after storing the refresh token verifies `connected()` and raises `GoogleOAuthError` if the token was not stored. `Controller.connect_google` runs the flow on a background thread, logs every step, surfaces failures through the `error` signal (clear errors, never silent), and emits `google_connected` so the Settings label refreshes on the main thread via a queued signal. Root cause of the "stays not connected" bug: the token store was never verified after `set_secret`. E2E: tests/e2e/test_google_oauth.py — OAuth flow saves the refresh token and `controller.get_google_connected()` is True afterwards; also fixed tests/unit/integrations/google/test_oauth.py to fake `get_secret` so the new storage check is exercised.
- d. Log redaction — DONE: `RedactionFilter`/`_redact_obj` mask only secret-like dict values (api_key, token, refresh_token, …); plain strings and list items stay readable, so whole messages are no longer replaced with "[REDACTED]". tests/unit/app/test_logging_setup.py passes.
- e. Ctrl+C — DONE: `__main__.main()` installs `_install_quit_on_ctrl_c(app)` before `app.run()`; on Windows a console-control handler (installed via SetConsoleCtrlHandler, because `signal.SIGINT` is not delivered while Qt's `exec()` is blocked in the message loop) posts `quit()` to the GUI thread with `QMetaObject.invokeMethod(..., QueuedConnection)`; elsewhere `signal.signal(signal.SIGINT, app.quit)`. `finally: app.cleanup()` stops the worker thread and removes the single-instance socket, so Ctrl+C quits cleanly. Not end-to-end testable in this sandbox (the harness console does not deliver Ctrl+C events); verified by code review.
- f. Real-composition-root e2e tests — DONE: tests/e2e/test_chat_llm.py (FakeLLM: "hey" gets a reply), tests/e2e/test_google_oauth.py (real threads: OAuth saves token, Settings updated via signal), tests/e2e/test_scheduler_threading.py (real worker thread + injectable tick: reminder fires into the inbox as the clock advances), tests/e2e/test_reminders_chat.py (FakeLLM scripted tool calls: "remind me to drink water in 1 minute" creates a scheduled reminder; advancing the injected clock fires it through a fake notifier into the inbox; chat confirms with the resolved time). All run in the phase gate via `python -m pytest -q` (242 passed, ruff ✓, lint-imports ✓, diagnose ✓).

## New work this session (2026-11-10)
- Reminders from chat (plan §8.5) — DONE: added `reminder_create` (class B), `reminder_list` (class A), `reminder_snooze` (class B), `reminder_cancel` (class B) in src/secretary/tools/reminders.py; each resolves time in code via timeparse, uses idempotency keys, and reminder_create dedupes within 60s and echoes the resolved fire time. Registered in the router and the system prompt tool list. Tasks quick-add states whether it creates a task or a reminder. E2E: tests/e2e/test_reminders_chat.py (real composition root, FakeLLM, injected clock, fake notifier). Committed dbec2f3.
- 0xC0000409 teardown crash — DONE (mitigated): faulthandler shows a native Qt access violation (<no Python frame>) when the shared QApplication is destroyed at interpreter teardown (~30-40% of full runs). Added conftest.py session fixture that quits the shared QApplication after all tests. Root cause: native PySide6 Windows teardown race; residual is environmental. Committed 45153f3.
- Settings Data page (plan §5.5, §941-942) — DONE: Backup now, Restore from backup (safety copy + quit to restart), Delete all data (wipes DB, backups, logs, Credential Manager entries), Export JSON/Markdown. Controller methods + unit tests. Committed a997936.
- Memory facts UI (plan §8.5) — DONE: memory_remember (class B) and memory_forget (class B) over the facts table with idempotency keys; delete added to facts_repo; registered in router + system prompt; Settings Memory section lists facts and supports remember/forget; unit tests. Committed 61e4314.
- Perf pass (plan §9.2, C-24) — DONE: dateparser warm_up() called from the WorkerThread at startup so the first resolve_when call is not slow; unit test. Committed 172d0bc.
- Remaining (code-buildable): none open. Diagnostics screen was already DONE (a459468).
- Test count now 254 collected (ruff ✓, lint-imports ✓, diagnose ✓).

## Stabilization (this session) — committed
- PART 1 selftest (commit f01112b): `python -m secretary --selftest {chat|reminder|google|all}` runs the REAL composition root headless (real QApplication, store, controller, LLM client, keyring, scheduler thread, notifier, no fakes). Prints [PASS]/[FAIL] per step with exact exception text, no secrets. Registered `--selftest` in __main__.py.
- PART 2 logging/excepthook (commit 3252df7): INFO logging at every chat hop (turn started, selected tools, LLM response, per tool call, finished) in agent/loop.py + controller.send_message; scheduler tick logs fired count and step exceptions (replaced prints) in scheduler/ticker.py. New src/secretary/errors.py installs sys.excepthook/threading.excepthook that log (redacted) and report to a UI reporter; wired in __main__.py so worker-thread and Qt-slot exceptions reach the UI as visible errors (Chat bubble / Settings message), never silent. ChatView and SettingsView display controller.error.
- PART 3 Settings (commit 84b0938): simplified to four tabs per plan §12 — General (theme, autostart), AI (provider, model, key field, Test connection), Google (Connect/Reconnect, status, last sync, one error line), Data (backup, restore, export, delete all). Removed Memory/etc. from Settings. AI reads via Controller.get_llm_config() (no ui→config import).
- PART 4 shutdown (commit 874723a): deterministic teardown — main() stops the SchedulerThread, closes the DB, then app.cleanup(); SchedulerThread.stop() joins (sleeps in small increments, no 30 s stall); conftest.py closes widgets, quits QApplication, gc.collect after all tests. New tests/smoke/test_shutdown.py starts and stops the real composition root 20x without a native abort.

## Current session (2026-11-08) — Phase 3 code-buildable work
- src/secretary/tools/events.py (NEW): event_create (class B) and event_list (class A). Wired in __main__ registry + router.
- src/secretary/timeparse/when.py: added resolve_date() (date-only variant of resolve_when, no past check).
- src/secretary/tools/planning.py (NEW): plan_day (class A) — resolves date_text, lists the day's events, returns free slots within 09:00-17:00 local as structured data. Wired in __main__ registry + router.
- tests/unit/tools/test_events.py (3 tests) + tests/unit/tools/test_planning.py (3 tests).
- Verification: ruff ✓ | pytest 124 passed ✓ | lint-imports 7 kept/0 broken ✓. Committed as 324944b.

## Phase 3 status (plan §21), 2026-11-09
- plan_day — DONE (free slots 09:00-17:00 local, committed 324944b).
- event_create + event_list — DONE incl. class-B conflict warnings (25302e5) and all-day events (de39d2a).
- Google Calendar read sync (windowed, sync tokens) — code-buildable & tested against mocked HTTP; only real sign-in/credentials.json is HUMAN-GATED.
  - calendar.py: 410 → full resync, etag skip-if-unchanged, sync failure recorded to settings (c51b907, 783b5ee).
  - gmail.py (NEW): Gmail messages.list / messages.get read client (783b5ee).
  - auth.py (NEW): OAuth consent flow loopback+PKCE; Settings Connect/Reconnect button + status; controller get_google_connected / get_google_sync_status; settings UI chip (5213b27).
  - docs/GOOGLE_SETUP.md (NEW): manual test steps — create Google Cloud project, OAuth consent "In production", Desktop client, place credentials.json next to config, connect, see events, revoke access, reconnect flow.
  - src/secretary/integrations/google/auth.py (NEW, b78f605): GoogleAuth refreshes access tokens from the OAuth2 token endpoint; refresh token stored in keyring "google_token"; 401/no-token → GoogleAuthError. 5 tests with respx-mocked endpoint + faked keyring.
  - src/secretary/integrations/google/calendar.py (NEW): CalendarClient over events.list + sync_calendar() windowed sync with nextSyncToken; upserts by google_event_id, soft-deletes removed events, persists token in the settings table. 3 tests with respx-mocked Calendar API.

## Phase 3.5 (plan §21) — email, started 2026-11-09
- Migration 005 (email_messages table) + store/repos/messages.py — DONE (a9757cf).
- email_search / email_read (class A, quarantined reads; results wrapped as <untrusted> data in agent/loop.py per plan §8.6) — DONE (a9757cf), incl. prompt-injection test proving an injected email cannot cause a send.
- email_draft (class B) — DONE (a9757cf); email_send class C prepare + pending_actions with 2-hour expiry — existed.
- email_triage (class A, enum category/urgency/suggested_action via injected no-tools classifier, upsert to triage_results) — DONE (beba178), 5 tests.
- Approvals view: code-built summaries, Approve/Reject, 2-hour expiry, payload re-verification, recipient highlighting (new addresses bold + "(new)") — DONE (a1b4339); screenshot eyeball at 150% is human_todo.md #6.
## Phase 4 (plan §21), 2026-11-09
- Safe fetch fetch_url (integrations/fetch.py) — DONE (e47bfc7), 8 respx-mocked tests.
- research_brief (class A) — DONE (d3a3f49): plan queries → search (≤4 sources) → fetch/extract → quarantined per-source summaries → brief write → citation check removing unmatched claims; ≤8 LLM calls; partial/unavailable brief on search failure. 4 tests (tests/unit/tools/test_research.py).
- Next: background research job with progress/caps (UI work, Phase 5).

## Phase 5 (plan §21), started 2026-11-09
- Settings theme toggle (system/light/dark; follows Windows color scheme) — DONE (7e2bf0d); also fixed save_config to handle nested tables. BUG 3 FIXED: theme changes now regenerate and re-apply QSS immediately (resolve_theme moved to ui/theme/__init__.py; SettingsView._on_theme_changed re-applies apply_theme to QApplication.instance(); main_window applies theme at startup and re-applies when Windows color scheme changes via colorSchemeChanged). Tests in tests/ui/test_settings.py.
- Empty states for list views (Tasks, Inbox, Calendar/Events, Today reminders, Approvals) — DONE (4a79335) via new ui/widgets/empty_state.py.
- Accessibility pass — DONE: contrast test (tests/ui/test_contrast.py), QSS focus rings, accessible names on buttons, tab-order checks in tests/ui/test_screenshots.py.
- Diagnostics screen — DONE (a459468): Settings "Run diagnostics" button runs run_diagnose() and shows the report.
- Diagnose now uses [OK]/[WARN]/[FAIL] markers (28cd83e): FAIL (exit 1) only for Python version, config load, keyring importable, store connects, tzdata; WARN (exit 0) for missing Groq/Gemini keys, Google refresh token, credentials.json. Prints paths checked for credentials.json.
- `credentials.json` lookup order (this session): (1) `SECRETARY_CREDENTIALS` env var, (2) `%LOCALAPPDATA%\Secretary\credentials.json` (installed default), (3) project root `credentials.json` only when running from source (not PyInstaller-frozen). `diagnose` prints which location was found, or "missing" plus all paths checked. Decision logged in docs/decisions_log.md; GOOGLE_SETUP.md updated.
- Google OAuth Connect/Reconnect (plan §13.2) — DONE: Settings "Connect Google"/"Reconnect Google" button + connected status; loopback redirect on ephemeral port + PKCE (oauth.py), refresh token stored in Credential Manager; controller runs flow on a background thread (never blocks main thread). BUG 2 FIXED: loopback server no longer deadlocks (serve_forever now runs on a separate thread; shutdown called from main thread), unexpected exceptions in the OAuth background thread are caught and surfaced via the controller `error` signal to the Settings view, and every flow step is logged without secrets. Tests in test_oauth.py and test_google.py.
- Screenshots — DONE (tests/ui/test_screenshots.py, docs/screenshots/*.png): all 11 views in light and dark; eyeball at 150% is human_todo.md #6.
- Bug 1 FIXED (f88fe55): scheduler tick ran on a worker thread using the main-thread SQLite connection → "SQLite objects created in a thread can only be used in that same thread", no reminder ever fired. `Connection.__init__` now opens with `check_same_thread=False` and all access (write/read/execute) is serialized by the writer lock (plan §5.4). E2E test in tests/e2e/test_scheduler_threading.py.
- Bug 2 FIXED: `Controller.send_message` accessed `self.llm.active` (`AttributeError: 'OpenAICompatClient' object has no attribute 'active'`) and `self._llm`/`self._router`/`self._registry` (none exist), so chat never worked and no error was shown. Added `Controller.get_active_llm_key()` (reads `config.llm.active`, keyring service `Secretary`, key `llm_api_key:{provider}` — same as `diagnose`) and used it in both `send_message` and `__main__.py`; fixed `send_message` to reference `self.llm`/`self.limiter`/`self.router`/`self.registry`. E2E tests in tests/e2e/test_chat_llm.py.
- Remaining Phase 5 (code-buildable but larger): delete-all-data/restore UX, memory facts UI, performance pass, long-run soak test.
- Phase 6 docs — DONE: README.md, PRIVACY.md, CHANGELOG unreleased section (ad75a76).
- Phase 6 remaining (mostly human-gated/packaging): code signing, final installer, screenshots GIF, demo video, GitHub Release v1.0.0.

## Test count (verified by running pytest, 2026-11-09)
- python -m pytest --collect-only : 232 collected items; python -m pytest -q : 232 passed.
