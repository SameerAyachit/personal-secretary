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

## CURRENT PRIORITY (A–E) — verified against code + fresh output, 2026-11-09 — ALL DONE
- A. SearchCache transaction fix — DONE: provider.py uses `Connection.write()`; db.py `write()` does BEGIN IMMEDIATE/COMMIT/ROLLBACK; `python -m secretary` opens main window offscreen.
- B. Smoke test tests/smoke/test_startup.py — DONE: builds real composition root, offscreen Qt + temp data root, passes in suite.
- C. lint-imports config — DONE: `[tool.importlinter]` + contracts in pyproject.toml; 7 kept, 0 broken (exit 0).
- D. `asyncio_default_fixture_loop_scope = "function"` — DONE: pyproject.toml [tool.pytest.ini_options].
- E. Test count — DONE: 125 collected, 125 passed (exit 0). "156" was an unverified claim (progress.md P2-07 line), never confirmed by running pytest.

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
- Settings theme toggle (system/light/dark; follows Windows color scheme) — DONE (7e2bf0d); also fixed save_config to handle nested tables.
- Empty states for list views (Tasks, Inbox, Calendar/Events, Today reminders, Approvals) — DONE (4a79335) via new ui/widgets/empty_state.py.
- Accessibility pass — DONE: contrast test (tests/ui/test_contrast.py), QSS focus rings, accessible names on buttons, tab-order checks in tests/ui/test_screenshots.py.
- Diagnostics screen — DONE (a459468): Settings "Run diagnostics" button runs run_diagnose() and shows the report.
- Diagnose now reports `llm_api_key:groq`, `llm_api_key:gemini`, `google_token` presence (never values) and `credentials.json` path/presence (539ff4f); `paths.credentials_path()` added.
- `credentials.json` lookup order (this session): (1) `SECRETARY_CREDENTIALS` env var, (2) `%LOCALAPPDATA%\Secretary\credentials.json` (installed default), (3) project root `credentials.json` only when running from source (not PyInstaller-frozen). `diagnose` prints which location was found, or "missing" plus all paths checked. Decision logged in docs/decisions_log.md; GOOGLE_SETUP.md updated.
- Google OAuth Connect/Reconnect (plan §13.2) — DONE (5213b27): Settings "Connect Google"/"Reconnect Google" button + connected status; loopback redirect on ephemeral port + PKCE (oauth.py), refresh token stored in Credential Manager; controller runs flow on a background thread (never blocks main thread). 13 tests (test_oauth.py, test_google.py).
- Screenshots — DONE (tests/ui/test_screenshots.py, docs/screenshots/*.png): all 11 views in light and dark; eyeball at 150% is human_todo.md #6.
- Remaining Phase 5 (code-buildable but larger): delete-all-data/restore UX, memory facts UI, performance pass, long-run soak test.
- Phase 6 docs — DONE: README.md, PRIVACY.md, CHANGELOG unreleased section (ad75a76).
- Phase 6 remaining (mostly human-gated/packaging): code signing, final installer, screenshots GIF, demo video, GitHub Release v1.0.0.

## Test count (verified by running pytest, 2026-11-09)
- python -m pytest --collect-only : 180 collected items; python -m pytest -q : 180 passed.
