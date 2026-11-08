# Changelog

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
