# Secretary

Native Windows personal secretary desktop app — PySide6 + SQLite + OpenAI-compatible
LLM. One process, one SQLite file (WAL), everything local except LLM/provider calls you
opt into. No web server, no browser UI, no HTTP endpoints.

## What it does

- **Reminders & tasks:** create from chat with natural language ("remind me to drink water
  in 1 minute"), times resolved in code via timeparse, snooze/ack/done, repeat alerts,
  dedup and idempotency keys.
- **Calendar:** create and list events with class-B conflict warnings (overlaps warned
  before insert), all-day events, `plan_day` for free slots 09:00–17:00.
- **Planner (code-assisted):** view free slots for any day and create a task in a chosen
  slot; all date math is done in code, never by the LLM.
- **Email (Phase 3.5):** local search/read, triage with enum categories
  (work/personal/newsletter/invoice/spam), drafts, approvals with code-built summaries and
  "(new)" recipient highlighting, send only after approval with 2-hour expiry and payload
  re-verification. Gmail triage job syncs recent messages and classifies them (real
  credentials human-gated).
- **Search & research (Phase 4):** web search (DuckDuckGo via ddgs, circuit breaker,
  cache), safe fetch (SSRF-safe, size cap), research briefs with per-source citations;
  unsupported claims are removed by a source-bound claim checker.
- **Inbox & notifications:** reminders fire into the inbox with toasts and a tray badge,
  catch-up on start, tray overflow hint ("+N more") when there are many unread items.
- **Native shell:** system tray, global hotkey (Ctrl+Alt+Space) quick capture,
  `--minimized` tray start, autostart via Windows Run key (Settings toggle or installer).
- **AI:** plug any OpenAI-compatible provider (Groq/Gemini/Ollama) via Settings; model
  dropdown from the provider; two-priority rate limiter keeps interactive chat ahead of
  background jobs; every turn runs on a worker event loop so the UI never blocks.
- **Google (optional, bring your own credentials):** OAuth connect/reconnect, Calendar
  `events.list` sync on the primary calendar only (the granted scope), Gmail read for
  triage. `calendarList` is intentionally never called.
- **Settings:** four tabs — General (theme, autostart), AI (provider, model, key),
  Google (connect/reconnect, sync chip), Data (backup, restore, export, delete all).
  Everything else lives in Diagnostics.
- **Hardening:** main-thread heartbeat watchdog (plan C-27) dumps tracebacks if the GUI
  thread stalls; timezone change banner; log redaction; class-C actions (send, bulk delete)
  go through `pending_actions` with code-built summaries.

## Getting started

```bash
# clone, then
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[test]"
python -m pytest -q
python -m secretary
```

- `python -m secretary --diagnose` runs configuration, store, and secrets checks.
- `python -m secretary --selftest {chat|reminder|google|google-live|notify|all}` runs the
  real composition root headless and reports `[PASS]`/`[FAIL]` per step; any `[FAIL]`
  exits non-zero (warnings stay non-fatal).
- `ruff check .` — lint; `lint-imports` — layering contracts (7 kept, 0 broken).

## Configuration

`config.toml` in the data root (`%LOCALAPPDATA%\Secretary` or `SECRETARY_DATA_ROOT`),
merged with defaults in `src/secretary/config.py`. Set the LLM provider key via Credential
Manager (Settings → AI → Test connection) — keys never live in config.

`credentials.json` (Google OAuth client) is looked up at `SECRETARY_CREDENTIALS`,
`%LOCALAPPDATA%\Secretary\credentials.json`, or the project root when running from
source.

## Privacy

See `PRIVACY.md`. Email/web/calendar text is quarantined from write tools; triage and
research run no-tools calls; keys live in Credential Manager, never in config or SQLite.

## Phases & status

Delivery is tracked in `personal_secretary_agent_master_plan.md` (plan §21) and
`docs/progress.md`. Human-gated items (live LLM key, clean-profile install, Google OAuth
credentials, code signing) are listed in `docs/human_todo.md`.

## Honesty

- Google is **optional** and **bring your own credentials**; the Calendar scope is
  `calendar.events` only, so `calendarList` is never used. A public release would need
  Google verification for wider distribution — out of scope.
- Public releases are **unsigned**; Windows SmartScreen may flag the installer.
- The heartbeat watchdog and UI tests guard the "python is not responding" freeze, but a
  real 7-day soak on a clean profile is still human-gated.

## Tests & quality

```bash
pytest -q            # all unit + UI (offscreen) tests
ruff check .         # lint
lint-imports         # layering contracts (7 kept, 0 broken)
```

## License

Private personal-use project.
