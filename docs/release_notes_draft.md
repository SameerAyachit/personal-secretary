# Secretary 0.2.0 (draft)

Windows only. Unsigned installer: SmartScreen may warn. Verify the installer against the published SHA-256 file.

## Highlights

- **Repeating events from chat**: "focus on my course every day 4pm to 6pm" creates a 30-day rolling series (kept topped up automatically), pushed to Google Calendar. Undo removes what has not reached Google.
- **Times are right**: bare times like "4pm" now parse, absolute times are no longer read as UTC (they used to land hours late), and a time that has passed today means its next occurrence.
- **No more mystery "step limit"**: when a tool fails, the chat says why in plain words and stops after two identical failures.
- **Better questions and calendar lookups**: "what meetings do I have next week" now lists instead of creating an event, and "remind me at 5" asks AM or PM instead of guessing ("tonight at 9" and "at 17" also work now).
- **Honest chat**: it no longer claims to have created, changed, sent or listed something it did not actually do.
- **Real email send, behind approval**: Approve sends through your Gmail, in the original thread for replies. Mail view has Draft reply and Create task buttons.
- **Tasks view**: filters, search, tick to complete, inline edit, delete. A reminder can belong to a task; Done offers to complete the task too.
- **Today screen**: reminders with Snooze/Done, approvals waiting, While-you-were-away, today's agenda, quick-add, Plan my day.
- **Privacy**: new Settings > Privacy tab. Chat, task, calendar and Gmail-triage text go to your AI provider; on NVIDIA's trial endpoint NVIDIA records inputs and outputs and may use them to improve its products.
- **Update notice**: once a day the app asks GitHub for the latest release number (anonymous, can be turned off in Settings > General). It never installs anything by itself.
- **Packaging and quality**: build script that refuses to succeed unless the built exe passes `--diagnose`; CI runs lint, types (core packages), tests, layering checks and a dependency audit; main screens are checked for overflow at 125% and 150% text size.

## Known limits

- Repeating events are separate Google events, not one recurring event; deleting the whole series in Google is manual. Repeating all-day events are not supported.
- The Calendar view is a plain list (no week strip yet); Tasks cannot be drag-reordered; Tasks search is a substring match.
- Typing checks (mypy) cover the core packages only; the UI/controller/tools packages are still being cleaned up.
- The live eval against NVIDIA's Nemotron model scored 38/42 before the fixes above; the re-run after them is not yet recorded.
- Not yet verified: a 7-day soak, a clean-profile install, a signed installer.

## Upgrading

Settings, data and keys stay in `%LOCALAPPDATA%\Secretary` and Credential Manager. Two database migrations (011 event series, 012 email reply threading) run automatically on first start. Make a backup first (Settings > Data > Back up now) if you want a way back.
