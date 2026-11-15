# Changelog

## [Unreleased]

### Added
- Config keys now take effect: `search.*` (breaker, cache TTL), `research.max_sources/max_llm_calls`, `notifications.toast/popup_card`, `pending_actions.*` TTLs, `google.window_*_days`, `backup.keep`, `llm.temperature_tools`.
- Calendar write-back: events created in chat are pushed to Google Calendar (migration 007, `sync_state`, idempotent retries); see ADR-003.
- `llm.max_output_tokens` config (default 2048); the agent loop honours `llm.max_steps` and `llm.turn_timeout_seconds`.
- Startup reminder catch-up and a due-backup check.
- Calendar: event_create class-B conflict warnings (overlaps warned before insert), all-day events, plan_day (free slots 09:00–17:00 local).
- Email (Phase 3.5): email_search/email_read (quarantined reads), email_triage (enum category/urgency/suggested_action), email_draft, email_send approval with 2-hour expiry and payload re-verification, prompt-injection test proving injected email cannot cause a send.
- Search/research (Phase 4): safe fetch (SSRF-safe, 1 MB cap, text/html|text/plain only, max 3 redirects, trafilatura extraction), research_brief pipeline with quarantined per-source summaries and citation check removing unmatched claims.
- UI (Phase 5): Settings theme toggle (system/light/dark following Windows color scheme), Settings autostart Run-key toggle, Settings diagnostics button, empty states for all list views, screenshots for all views in light and dark.
- Store: migration 005 (email_messages), migration 006 (triage_results).
- Tests: 193 passed; import-linter 7 kept, 0 broken; FakeLLM eval 100%.
- `app.hotkey` now sets the quick-capture hotkey (`parse_hotkey`; an invalid value falls back to Ctrl+Alt+Space with a warning).
- `llm.limits` `rpd`/`tpd` are honoured as daily meters (plan section 7.4); a used-up day raises `DailyLimitReached` with a clear message instead of waiting. Minute buckets with a 0 limit are skipped.
- (Superseded by `llm.thinking`, see Changed.) `llm.reasoning_effort` was sent to gpt-oss models only. Allowed values per the Groq reasoning docs: low, medium, high. Not yet verified live together with tool calls.
- `research.tokens_per_source` truncates each page and `research.token_budget` caps total page text fed to the model.
- `pending_actions.expired_retention_days`: the scheduler sweeper deletes expired actions older than that.

### Changed
- Approving a send now really sends the email through Gmail (`users.messages.send`, existing `gmail.compose` scope), off the GUI thread, after re-verifying the draft; the result (sent or the reason it failed) lands in the Inbox. Only the first approval click can send. See ADR-005.
- Chat research runs as a background job (migration 008, `research_briefs`): the chat answers at once, the brief appears in the Research tab (recent briefs list) and the Inbox when ready. Background jobs left running by a crash are marked failed at startup.
- LLM provider switched from Groq to NVIDIA NIM (ADR-004): default `nvidia` provider (`https://integrate.api.nvidia.com/v1`, model `nvidia/nemotron-3-ultra-550b-a55b`, key `llm_api_key:nvidia`), limiter defaults 40 requests/min and 10,000/day. New `llm.thinking` (default false) controls Nemotron thinking via `chat_template_kwargs.enable_thinking`; `OpenAICompatClient` gained a generic `extra_body`, and inline `<think>` traces are stripped from replies. `nvapi-` keys are redacted in logs.
- `Controller` split into mixins (`controller/data.py`, `controller/google.py`, `controller/llm_settings.py`); the public API is unchanged. `get_active_llm_key` still imports from `secretary.controller`.

### Removed
- Groq defaults (provider entry, `groq_*` limits, key diagnostics) and `llm.reasoning_effort`.
- `google.enabled` config key (never read; whether Google is connected is decided by the stored token).
- Unused config keys `tokens.*`, `app.language`, `app.quiet_hours_*` (old config files still load).
- Runtime `CREATE TABLE` for the search cache (migration 003 owns the table).

### Fixed
- Research: web search found no sources because `ddgs` returns `href`/`body` (the provider read `link`/`snippet`); a "No results found" answer no longer counts against the circuit breaker; searches and page fetches no longer block the shared worker loop; research LLM calls now go through the rate limiter (`MeteredClient`) and a provider HTTP 429 is retried (honouring `Retry-After`) instead of failing; saving the provider in Settings now also reaches research.
- Email: a drafted email never appeared in Approvals (the view was never refreshed after a chat turn or on navigation) and chat talked about a non-existent "outbox". Views now refresh when opened and after every turn; drafts are listed under Approvals > Drafts with Request send / Discard; the approval summary names the real recipient and subject (it used to say "to me").
- Inbox: choosing Ack/Snooze/Done made the item vanish with no way back. The Inbox has New / Snoozed / Acknowledged / Done / All filters, every row can be changed (including Reopen), and Snooze offers 10 minutes, 1 hour or tomorrow 9am.
- Settings > AI: the model dropdown stayed disabled and empty (the list was only requested when the provider *changed*), so saving the provider stored an empty model. It is now usable immediately with the configured model, loads the provider's list the first time the AI tab opens, and keeps your selection when the list arrives.
- A rejected API key (HTTP 401/403) now shows "The AI provider rejected the API key. Open Settings > AI and enter a valid key." instead of the raw provider error.
- Cancelled reminders still fired (and were counted by catch-up) because the due query ignored `deleted_at`.
- Reminder/event/plan tools defaulted to Asia/Kolkata and let the model pick the timezone; they now use the configured timezone, which the agent loop pins and hides from the model.
- Gmail triage passed the message id as the user id, so every message fetch returned 403.
- Google OAuth now verifies the redirect `state`; the quick-add hotkey no longer needs pywin32.
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
