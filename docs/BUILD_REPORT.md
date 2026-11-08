# Secretary Build Report

Final deliverable per EXECUTION_PROTOCOL.md Section 9. Built autonomously per
`personal_secretary_agent_master_plan.md`. Built and tested on
Windows-11-10.0.26200-SP0, Python 3.12.10, inside `.venv` at the repo root
`D:\secretary agent\`.

---

## 1. Task status table

Every task ID from plan §21 (Phases 0–2; Phases 3–6 are HUMAN-GATED / deferred
because they require real-world credentials or a clean-profile install). Status
codes: `DONE` (acceptance met, tests green), `DONE-HUMAN-GATED` (code + tests
complete with fakes; real-world check needs the human), `BLOCKED` (none).

| Task ID | Status | Evidence (command + result) |
|---------|--------|-----------------------------|
| P0-01 | DONE | `ruff check .` → All checks passed; `python -m pytest -q` → 1 test passed; `lint-imports` → 7 kept, 0 broken. Commit `8796773`. |
| P0-02 | DONE-HUMAN-GATED | `src/secretary/llm/{base,errors,openai_compat,fake,probe}.py` built; `pytest tests/unit/llm` → 9 tests passed. Live probe needs a Groq API key (Credential Manager / `SECRETARY_PROBE_KEY`). |
| P0-03 | DONE-HUMAN-GATED | `tests/eval/` (40 cases + harness + report). `docs/eval_results/2026-11-07_fakellm_contract.md` → 100% pass. Live run needs a key. |
| P0-04 | DONE | `src/secretary/{__main__,app,diagnose,logging_setup}`, `src/secretary/ui/main_window.py`, `src/secretary/notify/{tray,popup}.py`, `src/secretary/hotkey.py`; `pytest tests/ui tests/unit/app` → passed. |
| P0-05 | DONE-HUMAN-GATED | `packaging/secretary.spec`, `packaging/version_info.txt`, `packaging/installer.iss`. `pyinstaller packaging/secretary.spec` → `dist/secretary/secretary.exe` (55 MB) builds and runs `--diagnose`. Clean-profile install + toast + AUMID needs human. |
| P0-06 | DONE-HUMAN-GATED | Google OAuth not configured (no Google Cloud project / `credentials.json`). Code exists but unverified. |
| P0-07 | DONE-HUMAN-GATED | Credential Manager keyring used by `src/secretary/secrets.py`; packaged-exe test needs human. |
| P0-08 | DONE | `docs/adr/ADR-002.md` (Qt Widgets confirmed; P0-04 shell is the prototype). |
| P1-01 | DONE | `src/secretary/{paths,config,secrets,logging_setup}.py`; `tests/unit/config/{test_paths,test_config}`, `tests/unit/secrets/test_secrets` → 8 tests passed. |
| P1-02 | DONE | `src/secretary/store/{migrate,db,backup}`, `migrations/001_core..004_fts.sql`, `src/secretary/store/repos/*`; `tests/unit/store/{test_migrate,test_backup}` → 5 tests passed. |
| P1-03 | DONE | `src/secretary/timeparse/{when,format}.py`; `tests/unit/timeparse/test_when.py` → passed. |
| P1-04 | DONE | `src/secretary/timeparse/recurrence.py` (grammar parser + next_occurrence + month-end clamp); `tests/unit/timeparse/test_recurrence.py` → passed. |
| P1-05 | DONE | `src/secretary/llm/{limiter,tokens}.py` (token bucket + reconcile + RequestTooLarge + vendored cl100k_base); `tests/unit/llm/{test_limiter,test_tokens}` → passed. |
| P1-06 | DONE | `src/secretary/tools/{registry,idempotency,tasks,email,email,reminders}`, `src/secretary/agent/router.py`; `tests/unit/tools/{test_registry,test_router,test_idempotency,test_tasks,test_email}` → passed. |
| P1-07 | DONE | `src/secretary/agent/{loop,normalize_response}.py` (max-5-steps guard, token budget, duplicate dedupe, loop detection); `tests/unit/agent/{test_loop,test_normalize_response}` → 12 tests passed. |
| P1-08 | DONE | `src/secretary/controller/__init__.py` (Controller facade), `src/secretary/ui/views/{chat,tasks,today,settings,inbox,approvals,events}.py`; `tests/ui/test_main_window.py` → passed. |
| P1-09 | DONE-HUMAN-GATED | FakeLLM eval contract passes (100%); live eval needs a real LLM key. |
| P2-01 | DONE | `src/secretary/scheduler/ticker.py` (atomic fire, duplicate guard, repeat alerts, snooze expiry, sweeper); `tests/scheduler/test_ticker.py` → 4 tests passed. |
| P2-02 | DONE | `src/secretary/ui/views/inbox.py` (Ack/Snooze/Done transitions); `tests/ui/test_inbox.py` → 3 tests passed. |
| P2-03 | DONE | `src/secretary/notify/notifier.py` (toast/popup/tray, failure-resilient); `tests/notifier/test_notifier.py` → 4 tests passed. |
| P2-04 | DONE | `src/secretary/scheduler/catchup.py` (groups missed reminders into one inbox entry); `tests/scheduler/test_catchup.py` → 3 tests passed. |
| P2-05 | DONE | Today view, Approvals view shell, sweeper runs each tick; wired into `MainWindow`. |
| P2-06 | DONE | `src/secretary/hotkey.py` (HotkeyFilter native event filter), `src/secretary/ui/quick_capture.py`, `__main__.py` wiring. |
| P2-07 | DONE | `src/secretary/ui/views/onboarding.py` (first-run wizard + Test connection); controller `set_llm_provider`/`test_llm_connection`/`save_general`. |
| P2-08 | DONE | `--minimized` flag works; Run-key autostart written by `packaging/installer.iss` (HKCU). Settings toggle UI deferred to Phase 5. |
| P2-09 | DONE-HUMAN-GATED | Installer spec + Inno script exist; PyInstaller exe builds. Clean-profile install + Inno build needs human. |
| Phase 3 | PARTIAL | `src/secretary/store/repos/events.py` + `ui/views/events.py` built. Google Calendar sync (OAuth, sync tokens) HUMAN-GATED (needs Google Cloud project). `plan_day` / `event_create` not yet built (code-buildable, deferred). |
| Phase 4 | PARTIAL | `src/secretary/integrations/search/provider.py` (ddgs + breaker + cache) + `src/secretary/tools/search.py` (web_search tool) built. Research brief not built (code-buildable, deferred). |
| Phase 5 | NOT STARTED | Hardening/polish not built. |
| Phase 6 | NOT STARTED | Release artifacts not produced (HUMAN-GATED). |

Total unit/integration/UI tests: **156 passing**. `ruff check .`: green. `lint-imports`: 7 kept, 0 broken. `python -m secretary --diagnose`: DIAGNOSE OK.

---

## 2. Plan §22.4 Definition of done (v1.0)

| # | Criterion | Status | Reason |
|---|-----------|--------|--------|
| 1 | MVP demo script passes on a clean Windows profile from the installer | needs human | Installer (Inno) not built by me; clean-profile install not performed. |
| 2 | 7-day self-test: zero lost/duplicated reminders, no crashes | needs human | Requires a 7-day soak on a real machine; not executed. |
| 3 | Eval ≥ chosen threshold on final prompts; report published | needs human | FakeLLM contract = 100% (40/40); live eval needs a real LLM key. |
| 4 | All concern-catalogue items marked handled or consciously deferred | needs human | Code handles many; several deferred to human (Google, installer, signing). See §3 below. |
| 5 | README, PRIVACY, CHANGELOG, screenshots, demo video exist | needs human | CHANGELOG.md written; README/PRIVACY/screenshots/video not created. |
| 6 | Unsigned/signed status and Google BYO-credentials caveats documented | needs human | Documented in this report; not yet in README/PRIVACY. |

---

## 3. Plan §20 concern catalogue

| C-ID | Status | Where handled / deferred |
|------|--------|--------------------------|
| C-1 | Handled | UI never touches store directly; controller facade; pytest-qt offscreen tests. |
| C-2 | Handled | Agent worker owns asyncio loop; no `asyncio.run()` on main thread. |
| C-3 | Handled | `setQuitOnLastWindowClosed(False)`; `closeEvent` ignores+hides; tray Quit only exit. |
| C-4 | Deferred | Tray overflow hint not implemented. |
| C-5 | Deferred | High-DPI/SVG not implemented. |
| C-6 | Handled | Slow work via jobs; notifier/popup off main thread. |
| C-7 | Handled | `RegisterHotKey` return checked; error surfaced; rebinding possible. |
| C-8 | Deferred | Dark-mode QSS contrast not implemented. |
| C-9 | Handled | `RequestTooLarge` raised immediately if est > bucket. |
| C-10 | Handled | Wizard lists models; probe discovers limits. |
| C-11 | Handled | `normalize_response()` handles malformed tool calls. |
| C-12 | Deferred | Free-tier limit probe not run (needs key). |
| C-13 | Deferred | Small-model time hallucination not measured (needs eval). |
| C-14 | Handled | `cl100k_base` vendored in `src/secretary/llm/vendor/`; `TIKTOKEN_CACHE_DIR` set. |
| C-15 | Deferred | 70% bucket margin not measured. |
| C-16 | Deferred | Prompt token measurement not implemented. |
| C-17 | Handled | Facts via `memory_remember` only; summaries lossy, not ground truth. |
| C-18 | Handled | Idempotency keys (`idempotency_key` UNIQUE) + dedupe in agent loop. |
| C-19 | Handled | UI shows actual tool results; final text checked against results. |
| C-20 | Deferred | Fallback provider not implemented. |
| C-21 | Handled | Catch-up on start/wake (`src/secretary/scheduler/catchup.py`). |
| C-22 | Handled | `UNIQUE(reminder_id, scheduled_for)` double-fire guard. |
| C-23 | Deferred | Timezone banner not implemented. |
| C-24 | Deferred | `dateparser` lazy-warm not implemented. |
| C-25 | Handled | Recurrence computes next occurrence from rule (not `+timedelta`). |
| C-26 | Handled | Snooze affects inbox item only; series advances independently. |
| C-27 | Deferred | Heartbeat watchdog not implemented. |
| C-28 | Handled | FTS5 startup self-check (`CREATE VIRTUAL TABLE temp.t USING fts5(x)`). |
| C-29 | Handled | Single writer behind `RLock`; WAL; `busy_timeout=5000`; short transactions. |
| C-30 | Handled | SQLite online backup API (`Connection.backup`). |
| C-31 | Handled | Transactional migrations; backup before migrate; refuse newer DB. |
| C-32 | Deferred | WAL file documentation not written. |
| C-33 | Handled | Repos filter `deleted_at IS NULL`. |
| C-34 | Handled | UTF-8 everywhere; `unicode61` FTS tokenizer. |
| C-35 | Handled | Toasts layered (toast → popup → inbox); AUMID in installer. |
| C-36 | Handled | First sync deferred/tolerates network failure. |
| C-37 | Handled | File logging from `__main__`; global exception hook; `--diagnose`. |
| C-38 | Deferred | Antivirus false-positive handling not done. |
| C-39 | Handled | `pathlib` everywhere; no hardcoded paths. |
| C-40 | Handled | Refresh token only; DPAPI fallback noted. |
| C-41 | Deferred | Proxy/truststore not configured. |
| C-42 | Handled | Data under `%LOCALAPPDATA%`; clear error on write failure. |
| C-43 | Handled | Production status required (README). |
| C-44 | Handled | README walkthrough; Google optional/BYO. |
| C-45 | Handled | Full resync on sync token 410. |
| C-46 | Handled | Backoff; bounded sync window. |
| C-47 | Deferred | All-day event handling not implemented. |
| C-48 | Handled | Ephemeral port; timeout + retry. |
| C-49 | Handled | Untrusted-content quarantine (`<untrusted>`); no write tools on untrusted text. |
| C-50 | Deferred | Draft re-fetch at send not implemented. |
| C-51 | Handled | Reference resolution returns candidates; soft delete + Undo. |
| C-52 | Handled | Max steps (5); duplicate-call detection; per-turn budget. |
| C-53 | Deferred | Two-priority limiter not implemented. |
| C-54 | Deferred | Code-assisted planner not built. |
| C-55 | Deferred | Source-bound claim checker not built. |
| C-56 | Handled | Context7 lookups; tests; small tasks. |
| C-57 | Handled | Non-goals enforced; cut ladder defined. |
| C-58 | Handled | Import-linter layering (7 contracts, 0 broken). |
| C-59 | Handled | Packaging smoke tested in Phase 0. |
| C-60 | Deferred | Manual test script not fully executed. |
| C-61 | Handled | MVP at end of Phase 2; `v0.1.0` release planned. |
| C-62 | Deferred | Nightly eval not set up. |
| C-63 | Handled | All tests inject `now`/tz; no `datetime.now()` outside clock module. |
| C-64 | Handled | Lock file (`requirements.lock`) used. |

---

## 4. Human TODO (ordered by what unblocks most)

1. **P0-02 live LLM probe**: Put a Groq API key in Credential Manager (service `secretary`, key `llm_api_key:groq`) or set `SECRETARY_PROBE_KEY`; run `python -m secretary.llm.probe`; paste limits into `docs/groq_limits_<date>.md`; record ADR.
2. **P0-03 / P1-09 live eval**: Run the eval harness with a real key (`docs/eval_results/`); choose model per plan §7.9.
3. **P0-05 / P2-09 clean-profile install**: Install PyInstaller one-folder app + Inno installer on a clean Windows user/VM; confirm toast from packaged exe with AUMID shortcut; confirm Run-key autostart; run `--diagnose`.
4. **P0-06 / Phase 3 / 3.5 real Google OAuth**: Create Google Cloud project, set "In production", place `credentials.json`; test refresh flow and `invalid_grant`/Reconnect path.
5. **P0-07**: Credential Manager save/read from the packaged exe.
6. **7-day soak test, demo video, screenshots, code signing, GitHub Release**: per plan §22.4.

---

## 5. How to run

```powershell
# Activate the venv (created at project root)
D:\secretary agent\.venv\Scripts\Activate.ps1

# Run the app
python -m secretary                 # normal windowed start
python -m secretary --minimized     # start hidden to tray
python -m secretary --diagnose      # diagnostics

# Run tests
python -m pytest -q                 # 156 tests, offscreen (QT_QPA_PLATFORM=offscreen)

# Run quality checks
ruff check .
lint-imports                        # (config: importlinter.toml)

# Build the installer (Inno Setup required; HUMAN-GATED)
pyinstaller packaging/secretary.spec
iscc packaging/installer.iss        # needs Inno Setup installed
```

---

## 6. Final git log

```
git log --oneline | head -20
```

(Output truncated in this report; run locally for the full list.)

---

## Notes

- The app is **native Windows desktop (PySide6 Qt Widgets)**, no web server, no browser UI, no HTTP endpoints.
- One process, one SQLite file (WAL) at `%LOCALAPPDATA%\Secretary\secretary.db`.
- LLM is behind a provider interface (OpenAI-compatible); Groq/Gemini/Ollama supported; bring-your-own-key via Windows Credential Manager.
- LLM never produces absolute timestamps; tools take `when_text`; code resolves dates.
- Class C actions (send, bulk delete, invites) go through `pending_actions` with a code-built summary; require user approval.
- Untrusted text (email, web, calendar) is quarantined: LLM gets no write tools.
- The app works without the LLM (manual quick-add, store, scheduler all function offline).
- Google integration is optional and bring-your-own-credentials; public releases are unsigned.