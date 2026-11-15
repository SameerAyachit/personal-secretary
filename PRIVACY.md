# Privacy

Secretary is a local-first desktop app. Nothing leaves your PC unless you explicitly configure it to.

## What stays on your PC

- **All your data:** reminders, tasks, calendar events, inbox items, drafts, research briefs, and config live in a single SQLite file under your data root (`%LOCALAPPDATA%\Secretary` or `SECRETARY_DATA_ROOT`).
- **API keys:** stored only in Windows Credential Manager (via Python `keyring`), never in config files or logs.
- **Search extraction:** web pages are fetched and text-extracted locally with trafilatura.
- **Logs:** written to your data root; email/web/calendar text is redacted before logging.

## What is sent, and only when you configure it

- **LLM provider:** chat turns, tool arguments, email triage/summaries, and research briefs are sent to your configured LLM provider (OpenAI-compatible; the default is NVIDIA's hosted API at `integrate.api.nvidia.com`) only after you paste an API key in Settings → AI. The system prompt instructs the model that email/web/calendar text inside `<untrusted>...</untrusted>` is data, never instructions.
  - **NVIDIA trial terms:** NVIDIA's trial endpoint records inputs and outputs and may use them to improve its products. Do not send content that must stay private while using the trial endpoint, or switch to a provider whose terms you accept (ADR-004).
- **Web search:** search queries are sent to DuckDuckGo (ddgs) when you use search or research; your IP is visible to DuckDuckGo.
- **Google Calendar and Gmail:** only if you connect Google OAuth credentials (credentials.json, "In production" project). Calendar events are read via Google's API, and events you create in the app are written back to your Google Calendar. Gmail is read for triage. **An email is sent from your Gmail account only after you request the send and press Approve** in the Approvals view; the app shows the real recipient and subject first, and the result appears in the Inbox.

## What is never done

- No telemetry, analytics, or usage reporting of any kind.
- No content is used to train models unless you separately agree to your LLM provider's terms.
- No cloud sync of your Secretary data.

## Data retention

You control retention: tasks/reminders can be done/cancelled (soft delete), inbox items acknowledged, calendar events deleted. The only automatic deletion is clearing expired approval requests after the configured retention period. Settings → Data can back up, export or delete everything.

## Questions

See `docs/human_todo.md` and the plan (`personal_secretary_agent_master_plan.md`, §15 Security and privacy).