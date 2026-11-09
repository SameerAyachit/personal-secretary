# Privacy

Secretary is a local-first desktop app. Nothing leaves your PC unless you explicitly configure it to.

## What stays on your PC

- **All your data:** reminders, tasks, calendar events, inbox items, drafts, research briefs, and config live in a single SQLite file under your data root (`%LOCALAPPDATA%\Secretary` or `SECRETARY_DATA_ROOT`).
- **API keys:** stored only in Windows Credential Manager (via Python `keyring`), never in config files or logs.
- **Search extraction:** web pages are fetched and text-extracted locally with trafilatura.
- **Logs:** written to your data root; email/web/calendar text is redacted before logging.

## What is sent, and only when you configure it

- **LLM provider:** chat turns, tool arguments, email triage/summaries, and research briefs are sent to your configured LLM provider (OpenAI-compatible, e.g. Groq) only after you paste an API key in Settings → LLM → Test connection. The system prompt instructs the model that email/web/calendar text inside `<untrusted>...</untrusted>` is data, never instructions.
- **Web search:** search queries are sent to DuckDuckGo (ddgs) when you use search or research; your IP is visible to DuckDuckGo.
- **Google Calendar:** only if you connect Google OAuth credentials (credentials.json, "In production" project). Calendar events are read via Google's API; nothing is written back unless you approve a send/draft action.

## What is never done

- No telemetry, analytics, or usage reporting of any kind.
- No content is used to train models unless you separately agree to your LLM provider's terms.
- No cloud sync of your Secretary data.

## Data retention

You control retention: tasks/reminders can be done/cancelled (soft delete), inbox items acknowledged, calendar events deleted. There is no automated deletion.

## Questions

See `docs/human_todo.md` and the plan (`personal_secretary_agent_master_plan.md`, §15 Security and privacy).