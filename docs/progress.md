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

## Phase 3 remaining (plan §21)
- conflict warnings on reminders/events — code-buildable, next.
- Google Calendar read sync (windowed, sync tokens) — HUMAN-GATED (needs credentials.json / Google Cloud project).

## Next: Phase 3.5 → 4 → 5 → 6 per plan §21 after Phase 3 code-buildable items.

## Test count (resolves 156 vs ~117)
- python -m pytest --collect-only : 124 collected items; python -m pytest -q : 124 passed.
- The "156 tests" in docs/progress.md (P2-07 line) was not verified by running pytest (protocol §3). Actual verified count: 124.

## P2-08 (Settings autostart toggle) — DONE (code), 2026-11-09
- src/secretary/autostart.py (NEW): Read/write the HKCU Run key value "Secretary" with data "<exe> --minimized", matching packaging/installer.iss (plan Appendix E); Windows-only, faked in tests.
- src/secretary/controller/__init__.py: get_autostart() / set_autostart() delegate to autostart module.
- src/secretary/ui/views/settings.py: real Settings view — General section + "Start Secretary at login" checkbox (accessible name "Start at login"), reflects true Run-key state, reverts on write failure; refresh_autostart() when the rail opens Settings.
- src/secretary/ui/main_window.py: SettingsView(controller) wired; refresh on Settings rail selection.
- tests/unit/test_autostart.py (6 tests), tests/ui/test_settings.py (5 tests), tests/ui/test_screenshots.py, tests/ui/test_contrast.py (token contrast both themes).
- Verification: ruff ✓ | pytest 140 passed ✓ | lint-imports 7 kept/0 broken ✓.
- Not automatable here: actual reboot autostart — covered by human_todo.md #3 (clean-profile install) and #6 (screenshot eyeball).

## Next: Phase 3 (plan §21) — calendar/events repo + view already built; Google Calendar sync is HUMAN-GATED.
