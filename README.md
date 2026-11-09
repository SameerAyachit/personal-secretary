# Secretary

Native Windows personal secretary desktop app — PySide6 + SQLite + OpenAI-compatible LLM. One process, one SQLite file, everything local except LLM/provider calls you opt into.

## What it does

- **Reminders & tasks:** create with natural language ("add a task to submit the lab report by Friday"), snooze/ack/done, repeat alerts.
- **Calendar:** create and list events with class-B conflict warnings (overlaps warned before insert), all-day events, `plan_day` for free slots 09:00–17:00.
- **Email (Phase 3.5):** search/read, triage with enum categories (work/personal/newsletter/invoice/spam), drafts, approvals with code-built summaries, send only after approval with 2-hour expiry and payload re-verification.
- **Search & research (Phase 4):** web search (DuckDuckGo via ddgs, circuit breaker, 24h cache), safe fetch (SSRF-safe, 1 MB cap, text/html+text/plain only), research briefs with citations.
- **Inbox & notifications:** reminders fire into the inbox with toasts and tray badge, catch-up on start.
- **Native shell:** system tray, global hotkey (Ctrl+Alt+Space) quick capture, `--minimized` tray start, autostart via Windows Run key (Settings toggle or installer).

## Getting started

```bash
# clone, then
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[test]"
python -m pytest -q
python -m secretary
```

`python -m secretary --diagnose` runs configuration, store, and secrets checks.

## Configuration

`config.toml` in the data root (`%LOCALAPPDATA%\Secretary` or `SECRETARY_DATA_ROOT`), merged with defaults in `src/secretary/config.py`. Set the LLM provider key via Credential Manager (Settings → LLM → Test connection) — keys never live in config.

## Privacy

See `PRIVACY.md`.

## Phases

Delivery is tracked in `personal_secretary_agent_master_plan.md` (plan §21) and `docs/progress.md`. Human-gated items (live LLM key, clean-profile install, Google OAuth credentials, code signing) are listed in `docs/human_todo.md`.

## Tests & quality

```bash
pytest -q            # all unit + UI (offscreen) tests
ruff check .         # lint
lint-imports         # layering contracts (7 kept, 0 broken)
```

## License

Private personal-use project.