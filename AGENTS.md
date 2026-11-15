# Secretary: rules for coding agents

## Source of truth
Follow `personal_secretary_agent_master_plan.md` in the project root (`D:\secretary agent\`). If code and plan disagree, stop and ask.
Work procedure: follow `EXECUTION_PROTOCOL.md` in the root.

## Hard rules
- Native PySide6 app. No web server, no browser UI, no HTTP endpoints.
- One process, one SQLite file. All SQL lives in `src/secretary/store/`.
- Layering: `ui → controller → agent → tools → store/integrations`. Lower layers never import upper ones. `lint-imports` must pass.
- Never touch widgets off the main thread. Never block the main thread.
- LLM never produces absolute timestamps. Tools take `when_text`; code resolves (timeparse/).
- Secrets only via `keyring`. Never in config.toml, `.env`, logs, or SQLite.
- Every schema change = new numbered file in `migrations/`. Never edit an applied migration.
- Class C actions (send, bulk delete, attendees) always go through `pending_actions` with a code-built summary.
- Untrusted text (email, web, calendar) goes only to tool-less LLM calls.
- No new dependency without an entry in `docs/deps.md` and my approval.

## Workflow
1. Read the relevant plan section. State the task and acceptance criteria.
2. Write/adjust tests first. 3. Implement. 4. Run: `ruff check`, `pytest -q`, `lint-imports`.
5. Update `docs/adr` or `CHANGELOG.md` if a decision changed.
6. Before using any Qt/WinRT/Google/NVIDIA API, look it up with the docs MCP. Do not guess signatures.

## Style
Type hints everywhere, pydantic for external data, small functions, no `print()` (use logging), no global state outside `app.py`.
