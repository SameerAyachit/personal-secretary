# Dependencies

Pinned in `requirements.lock` (plan §4.1). Every entry here traces to a plan concern or stack choice.

| Package | Version | Plan reference | Reason |
|---|---|---|---|
| PySide6 | 6.12.0 | §4.1 UI | Qt Widgets native desktop UI |
| httpx | 0.28.1 | §4.1 HTTP | Sync HTTP client inside the worker |
| dateparser | 1.5.0 | §4.1 Dates | Natural-language time parsing |
| python-dateutil | 4.0.0 | §4.1 Dates | rrule recurrence |
| tzdata | 2026.6 | §4.1 Dates | zoneinfo data on Windows |
| tiktoken | 0.14.0 | §4.1 Token estimate | cl100k_base token counting (vendored) |
| keyring | 25.7.0 | §4.1 Secrets | Windows Credential Manager |
| desktop-notifier | 6.2.0 | §4.1 Notifications | Windows toasts (with QSystemTrayIcon fallback) |
| pydantic | 2.14.3 | §4.1 Schema validation | Tool args, config, settings |
| ddgs | 9.16.1 | §4.1 Search | DuckDuckGo search behind provider interface |
| trafilatura | 2.3.1 | §4.1 Page text extraction | Research brief extraction |
| google-api-python-client | 2.201.0 | §4.1 Google (optional) | Google Calendar / Gmail API |
| google-auth-oauthlib | 1.5.0 | §4.1 Google (optional) | OAuth flow |
| PyInstaller | 6.22.3 | §4.1 Packaging | One-folder Windows exe |
| pytest, pytest-qt, pytest-asyncio, respx, time-machine, hypothesis | various | §4.1 Tests | Test suite |
| ruff, mypy, import-linter, pre-commit | various | §4.1 Quality | Lint, types, import layering, pre-commit |
| pip-audit | latest (CI only) | Plan §18 supply chain | Scans `requirements.lock` for known vulnerabilities in the CI `audit` job. Installed only on the CI runner, not in `requirements.lock`, never shipped. Approved with the 2026-11-15 improvement plan. |

No dependency may be added without a row here (and a line in `docs/human_todo.md` if the human must approve).
