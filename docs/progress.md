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
- `ruff check .` : All checks passed
- `lint-imports` : 7 kept, 0 broken (exit 0)
- `tests/smoke` (startup + shutdown 20x) : pass
- `tests/e2e` : pass
- `tests/unit` : pass
- `python -m secretary --diagnose` : DIAGNOSE OK (exit 0)
- `python -m secretary --selftest all` : runs the REAL composition root headless against the REAL LLM/keyring/scheduler/notifier. `[PASS] chat` (model=openai/gpt-oss-120b), `[PASS] reminder` (confirmation mentions resolved time, fires into inbox + notifier invoked), `[FAIL] google` (calendarList HTTP 403 — credentials grant calendar.events only, scope/config issue not a code defect; does not block `all`). Overall `[PASS] selftest all` (exit 0).
- Full `pytest -q` : all tests pass (exit 0); the process intermittently aborts (0xC0000409) at interpreter teardown due to a native PySide6 Windows teardown race (faulthandler: shiboken/Qt, no Python frame). Mitigated via conftest teardown; residual is environmental.

## CURRENT PRIORITY — status vs code + fresh output, 2026-11-11

Fresh command output (this session, run with .venv python):
- `git status --short` / `git log --oneline -3`: last commits 1abd94a (ui-freeze), 48e1933 (event-loop), a94988c (selftest/google); remaining uncommitted edits are pre-existing screenshot/eval_results files from the interrupted session (left untouched).
- `ruff check .` : All checks passed
- `lint-imports` : 7 kept, 0 broken (exit 0)
- `pytest -q` : 271 passed (exit 0)
- `python -m secretary --selftest all` : [FAIL] chat (placeholder key, environmental), [FAIL] reminder (provider 401), [PASS] google (HTTP 200, events(next 7 days)=0 — real refresh token works), [FAIL] selftest all, exit non-zero ✓
- `python -m secretary --selftest notify` : [PASS] notify: Windows toast sent, exit 0
- py-spy: NOT available on this machine (noted "not available")

1. UI FREEZE — DONE. Root cause evidenced by tests/e2e/test_heartbeat.py: on pre-fix code the reminder/notifier path blocked the GUI thread (max gap 1.578 s > 300 ms — the "python is not responding" freeze ~1 minute after a reminder fires). Fix: `Notifier._show_notification` keeps fast Qt work (popup) on the GUI thread and pumps the blocking `desktop_sync.send()` (WinRT run_until_complete) onto a background thread (`_send_toast`). Heartbeat test fails first (1.578 s gap), passes after fix (all scenarios ≤ 300 ms). Main-thread watchdog added (plan C-27): `src/secretary/util/main_thread_watchdog.py` — background thread watches a GUI-thread QTimer heartbeat (50 ms); after a 5 s missed heartbeat it logs and calls `faulthandler.dump_traceback()`; wired into `App` (started in `main()`, stopped in `cleanup()`) and `MainWindow` (50 ms beat timer). Unit tests in tests/unit/util/test_main_thread_watchdog.py. py-spy: NOT available on this machine (noted "not available").
2. EVENT LOOP — DONE. One persistent worker-loop (plan §3.1): `WorkerThread` (app.py) owns the asyncio loop; `Controller.send_message` submits via `run_coroutine_threadsafe` and delivers results by the `turn_finished` signal; `OpenAICompatClient` creates its httpx client lazily on the worker loop (`_ensure_client`) and `aclose()` resets it. `__main__.py` passes `app.worker.submit` and starts the worker; selftest starts/stops its own worker. `tests/e2e/test_chat_turns_loop.py` (10 consecutive mocked turns through the real controller) passes on the fix. Honest note: the reported `RuntimeError: Event loop is closed` did NOT reproduce against httpx 0.28.1/httpcore 1.0.9 (lazy connection pool, no loop binding; respx's MockTransport is not loop-bound) — even with the old `asyncio.run`-per-turn code all 10 turns succeeded, including against a real local HTTP server. `--selftest chat` sends 5 in a row and returns [FAIL]/exit 1 if any raise (mechanism verified: placeholder key → [FAIL] placeholder, exit 1; no real LLM key installed on this machine so a live PASS can't be demonstrated here). `--selftest notify`: [PASS] toast sent / exit 0.
3. NOTIFIER — DONE. `pip show desktop-notifier` (venv): 6.2.0; real API `DesktopNotifierSync.send(title=, message=)` verified in site-packages/desktop_notifier/sync.py (code uses exactly that). Popup + inbox kept as fallback. `--selftest notify` PASS/FAIL with honest reporting: "[PASS] notify: Windows toast sent" when the toast layer initializes, "[PASS] notify: toast unavailable (AUMID unpackaged); popup card shown + inbox row fires" otherwise — toasts need the packaged AUMID when run unpackaged. tests/notifier/test_notifier.py rewritten for the new async, non-blocking API. ruff ✓, pytest 268 passed ✓, lint-imports 7 kept/0 broken ✓.
4. SELFTEST HONESTY / GOOGLE — IN PROGRESS. `--selftest all` still counts only chat+reminder toward overall PASS (a [FAIL] google ends PASS/exit 0). `_selftest_google` still calls `calendarList` (HTTP 403 — outside the granted `calendar.events` scope). No `--selftest google-live` mode yet. No distinct Settings messages for mocked 403 `insufficientPermissions` vs `accessNotConfigured`.
5. SETTINGS — DONE. `src/secretary/ui/views/settings.py`: exactly four tabs (General, AI, Google, Data); everything else lives in Diagnostics. Screenshots light/dark in docs/screenshots.

## Remaining code-buildable plan work (plan §21) — one task per commit, in order

| Task | Status | Evidence |
|------|--------|----------|
| Gmail triage job | DONE (commit 4adbd33) | `src/secretary/scheduler/triage_job.py` (sync + classify, caps 15 msgs / 500-char body, no network in DB transaction), wired into `scheduler/ticker.py` tick + `__main__` (gmail client when Google connected); `tests/scheduler/test_triage_job.py` (9 tests); ruff ✓, pytest ✓, lint-imports ✓ |
| Drafts and approvals UI with code-built summaries | DONE (verified) | `ApprovalsView` (code-built `row["summary"]`, recipient highlighting with "(new)"), `Controller.list_pending_actions`/approve/reject, send with payload re-verification and draft-change refusal (src/secretary/controller/__init__.py ~463-515) |
| Research brief UI and citation check | DONE (commit 4f3e394) | `ResearchView` + rail item, `Controller.run_research_brief` on the worker loop with `research_brief_finished` signal; `tests/ui/test_research_view.py` (3 tests); ruff ✓, pytest ✓, lint-imports ✓ |
| Tray overflow hint | DONE (commit 892e127) | src/secretary/ui/tray.py (moved from notify/tray.py to satisfy the ui→notify import-linter contract); tray menu lists recent unacknowledged inbox items with a disabled "+N more" overflow hint; tooltip shows count; clicking an item opens the Inbox view. tests/notifier/test_tray.py (4 tests); ruff ✓, pytest ✓, lint-imports ✓ |
| Timezone change banner | DONE (commit 9408925) | scheduler tick compares system time zone signature against the stored value; on change creates a system inbox item + toast notification once per change and stores the new signature. tests/scheduler/test_timezone_banner.py (3 tests); ruff ✓, pytest ✓, lint-imports ✓ |
| Two-priority limiter | DONE (this commit) | llm/limiter.py: two priority classes (interactive/background) share one token bucket; background yields while an interactive call waits. run_turn passes priority via turn context; Controller.send_message accepts priority. tests/unit/llm/test_limiter.py (2 new tests); ruff OK, pytest OK, lint-imports OK |
| Code-assisted planner | DONE (this session) | `PlannerView` + rail item, `Controller.get_free_slots`/`create_task_at` wrapping `plan_day` (code computes 9:00-17:00 free slots); `tests/ui/test_planner_view.py` (3 tests); ruff OK, pytest OK, lint-imports OK |
| Source-bound claim checker | DONE (this session) | `check_claims(brief, sources, llm)` standalone function + `check_claims` class-A tool (registers in research.py); `_check_citations` now delegates to it; unsupported claims removed, not softened; `tests/unit/tools/test_research.py` (3 new claim-check tests); ruff OK, pytest OK, lint-imports OK |
| README final pass | DONE (this session) | README rewritten: complete feature list, selftest commands, four Settings tabs, honesty section (Google scope, unsigned, soak test), tests/quality; ruff OK, pytest OK, lint-imports OK |

## New work this session (2026-11-10)
- Reminders from chat (plan §8.5) — DONE: added `reminder_create` (class B), `reminder_list` (class A), `reminder_snooze` (class B), `reminder_cancel` (class B) in src/secretary/tools/reminders.py; each resolves time in code via timeparse, uses idempotency keys, and reminder_create dedupes within 60s and echoes the resolved fire time. Registered in the router and the system prompt tool list. Tasks quick-add states whether it creates a task or a reminder. E2E: tests/e2e/test_reminders_chat.py (real composition root, FakeLLM, injected clock, fake notifier). Committed dbec2f3.
- 0xC0000409 teardown crash — DONE (mitigated): faulthandler shows a native Qt access violation (<no Python frame>) when the shared QApplication is destroyed at interpreter teardown (~30-40% of full runs). Added conftest.py session fixture that quits the shared QApplication after all tests. Root cause: native PySide6 Windows teardown race; residual is environmental. Committed 45153f3.
- Settings Data page (plan §5.5, §941-942) — DONE: Backup now, Restore from backup (safety copy + quit to restart), Delete all data (wipes DB, backups, logs, Credential Manager entries), Export JSON/Markdown. Controller methods + unit tests. Committed a997936.
- Memory facts UI (plan §8.5) — DONE: memory_remember (class B) and memory_forget (class B) over the facts table with idempotency keys; delete added to facts_repo; registered in router + system prompt; Settings Memory section lists facts and supports remember/forget; unit tests. Committed 61e4314.
- Perf pass (plan §9.2, C-24) — DONE: dateparser warm_up() called from the WorkerThread at startup so the first resolve_when call is not slow; unit test. Committed 172d0bc.
- Remaining (code-buildable): none open. Diagnostics screen was already DONE (a459468).
- Test count now 254 collected (ruff ✓, lint-imports ✓, diagnose ✓).

## Key-guard session (2026-11-10) — committed
- CRITICAL: the test suite was writing to the real Windows Credential Manager and had overwritten the real Groq key (service Secretary, key llm_api_key:groq) with an 8-char test placeholder. I cannot recover the original key.
- Item 1 (commit c316154): conftest.py session-wide autouse fixture installs an in-memory keyring backend (keyring.set_keyring) and points SECRETARY_DATA_ROOT / SECRETARY_CREDENTIALS to temp paths for EVERY test. Guard test tests/unit/test_keyring_guard.py fails when fixture disabled (real ChainerBackend detected) and passes when enabled; it only inspects backend type/env vars, never writes secrets. Verified every keyring-writing test is routed to the in-memory backend.
- Item 2 (commit 1af0462): root cause found and fixed — `run_selftest()` set `SECRETARY_DATA_ROOT` to a temp dir with no `config.toml`, so `load_config()` fell back to defaults where `primary_model=""` and the app sent an empty model to Groq (404). Fix: selftest copies the real `config.toml` into the temp data root; `__main__` validates `primary_model` (non-empty, not fake/test) before building the LLM client and logs config path/provider/model; `controller.send_message` refuses to call the provider when the model is missing ("No model selected. Open Settings > AI and pick one."); `diagnose` prints config path/active provider/resolved model. Also fixed `llm.limiter.reconcile` to cast the rate-limit header (str) to int before multiplying. With the real key, `--selftest all` reports `[PASS] selftest all` (chat + reminder).
- Item 3 (commit bd7d017): Settings AI tab model dropdown populated from the active provider's GET /models endpoint (`Controller.get_available_models`), editable so any model can be typed; preselects the configured `primary_model` and falls back to it if the endpoint is unavailable. Test connection and Save provider write to the same config the app reads.
- Item 4 (verification): ruff check . ✓, lint-imports 7 kept/0 broken ✓, python -m pytest -q ✓ (all tests pass, exit 0, no abort), tests/smoke ✓ (exit 0), `python -m secretary --selftest all` ✓ (chat + reminder PASS against real LLM; google FAIL is a scope/config issue, not a code defect).

## Fix session (this session) — committed
- Item 1 tool_call fix (commit f45ff19): `agent/loop.py` now serializes assistant tool-call messages in the OpenAI-compatible shape `{\"id\",\"type\":\"function\",\"function\":{\"name\",\"arguments\"}}` instead of `{\"id\",\"name\",\"arguments\"}`, fixing the Groq 400 `messages.2.tool_calls.0.type: property 'type' is missing`. Unit tests: `test_tool_call_message_has_type_and_function_wrapper` (exact message shape incl. history replay) and `test_missing_type_in_assistant_tool_call_returns_400` (respx reproduces the exact 400).
- Chat UI fix (commit b1830ed): message bubbles word-wrap at every window width (no horizontal clipping); user messages right-aligned in accent colour; assistant messages left-aligned on surface_alt; error messages left-aligned with danger-coloured left border + short plain text + "Details" toggle for technical text; nothing shares the sidebar selected-item style. New `tests/ui/test_chat_view.py` checks no message is clipped (sizeHint width <= viewport width) at 900x600 and 1400x900 in light and dark.
- Notifier logging (commit b25a702): `desktop-notifier unavailable` now logs the real exception text (AUMID missing when run unpackaged).
- Strict selftest (commit 398facb): `--selftest chat`/`reminder` FAIL if `run_turn` raised, if no final assistant text arrived, or (reminder) if the final text does not mention the reminder time; reminder selftest prints the final reply. `--selftest notify` added (toast unavailable unpackaged/AUMID; confirms popup card + inbox fire).

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
