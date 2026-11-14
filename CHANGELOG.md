# Changelog

## [Unreleased]

### Added
- Calendar write-back: events created in chat are pushed to Google Calendar (migration 007, `sync_state`, idempotent retries); see ADR-003.
- `llm.max_output_tokens` config (default 2048); the agent loop honours `llm.max_steps` and `llm.turn_timeout_seconds`.
- Startup reminder catch-up and a due-backup check.
- Calendar: event_create class-B conflict warnings (overlaps warned before insert), all-day events, plan_day (free slots 09:00–17:00 local).
- Email (Phase 3.5): email_search/email_read (quarantined reads), email_triage (enum category/urgency/suggested_action), email_draft, email_send approval with 2-hour expiry and payload re-verification, prompt-injection test proving injected email cannot cause a send.
- Search/research (Phase 4): safe fetch (SSRF-safe, 1 MB cap, text/html|text/plain only, max 3 redirects, trafilatura extraction), research_brief pipeline with quarantined per-source summaries and citation check removing unmatched claims.
- UI (Phase 5): Settings theme toggle (system/light/dark following Windows color scheme), Settings autostart Run-key toggle, Settings diagnostics button, empty states for all list views, screenshots for all views in light and dark.
- Store: migration 005 (email_messages), migration 006 (triage_results).
- Tests: 193 passed; import-linter 7 kept, 0 broken; FakeLLM eval 100%.

### Fixed
- Chat: turn ids were per-launch counters, so the same reminder request in a new session was deduped against an old reminder and never fired; they are now unique.
- Chat: Settings > AI save built a 1-token rate limiter when config limits were 0 ("meter disabled"); limits of 0 now mean no local limiter.
- Chat: Send is disabled while a turn runs; errors render as error bubbles; provider tool schemas no longer carry non-standard keys.
- Notifications: one tray icon (with a real icon) instead of two invisible ones; tray Quit works; popup Done/Snooze act on the inbox item; popup stacking fixed; tray-message fallback when toasts are unavailable.
- Google: connecting mid-session now starts sync without a restart; Calendar view refreshes after sync and chat events.
- config.save_config wrote nested dicts as strings (broke config reload).
- SearchCache used bare COMMIT on an isolation_level=None connection (crashed startup).
- lint-imports config location (now read from pyproject.toml).

## [0.1.0] - 2026-11-08

### Added
- Native PySide6 (Qt Widgets) desktop app, single process, one SQLite (WAL) file.
- Repo skeleton, opencode skills/commands/agents, AGENTS.md, ADR-001 (D1-D15), ADR-002 (Qt Widgets).
- LLM layer: OpenAI-compatible client, FakeLLM, rate limiter with token bucket + reconcile, vendored cl100k_base token counting.
- Store: forward-only migration runner (schema_migrations), migrations 001-004 (tasks, reminders, inbox, pending_actions, action_log, events, facts, settings, conversations, messages, llm_usage, search_cache, FTS5), online backup/restore, typed repositories.
- Configuration (config.toml + Appendix A defaults), secrets via keyring (Credential Manager), JSON-lines logging with redaction.
- Time/date: resolve_when (dateparser, DMY, RELATIVE_BASE, AmbiguousTime/PastTime, synonyms), recurrence grammar parser + next_occurrence (rrule, month-end clamp).
- Agent: tool registry with safety classes A/B/C, keyword router, idempotency keys, normalize_response (Appendix C), run_turn loop with step/timeout/loop guards.
- Tools: task_create (Class B), task_list (Class A), email_send (Class C → pending_actions).
- Qt shell spike: QApplication (setQuitOnLastWindowClosed=False), single-instance QLocalServer, WorkerThread (asyncio loop), tray icon, frameless popup card, global hotkey (win32 guard), diagnose, --minimized.
- Packaging: PyInstaller one-folder spec (tzdata, vendored tiktoken, migrations), Inno Setup installer (HKCU Run key autostart).
- Eval harness: 40 starter cases, FakeLLM contract, dated reports.
- Tests, CI workflow (ruff, pytest offscreen, lint-imports), import-linter layering contracts.

### Human-gated (real key / clean profile / Google credentials)
- P0-02 live LLM probe (docs/groq_limits_<date>.md).
- P0-03/P1-09 live eval against a real model.
- P0-05 clean-profile install + toast from packaged exe + Run-key autostart.
- P0-06 Google OAuth ("In production" + credentials.json).
- P0-07 Credential Manager from the packaged exe.
