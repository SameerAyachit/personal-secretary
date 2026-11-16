# Release how-to

Steps that need you, a clean Windows profile, or a certificate. Commands are PowerShell from the project folder unless noted.

## Done on 2026-11-16
- Deleted the plaintext `%LOCALAPPDATA%\Secretary\google_token.json` (the app reads its Google token from Credential Manager; `--diagnose` no longer warns). Deleting a file does not revoke the token inside it: to kill the old refresh token, remove the app at https://myaccount.google.com/permissions and press Reconnect in Settings > Google.
- Deleted the placeholder Credential Manager entry `Secretary` / `llm_api_key:groq`.
- Kept `llm_api_key:gemini`: it looks like a real key (53 characters, no placeholder words). If you do not use Gemini: `.venv\Scripts\keyring.exe del Secretary llm_api_key:gemini`. Never delete `llm_api_key:nvidia` or `google_token`.

## 7-day soak
1. Build and install: `powershell -File packaging\build.ps1 -Installer`, then run `packaging\Output\Secretary-Setup-<version>.exe`, ideally on a clean Windows user. Tick "Start at login".
2. Use it for real for 7 days: a few reminders a day (one repeating), one repeating event, tasks, a research brief, and Google connected.
3. Once a day: `python scripts/soak_check.py --days 1` (read-only; add `--days 7` at the end). It lists ERROR lines, main-thread stalls, reminders fired, silences over 5 minutes between scheduler ticks, database size and memory of `secretary.exe`. Silences while the PC was off or the app was closed are expected; a silence while it was running is not.
4. Also check by eye: every reminder arrived on time (toast and Inbox), memory in Task Manager is not growing day after day, the window never says "Not responding".
5. Pass = 7 days with no crash, no freeze, no missed reminder and no unexplained ERROR. Write the result and date in `docs/progress.md`. Until then the release notes say the soak is not done.

## Sign the installer (optional)
Unsigned installers work but Windows SmartScreen warns. To sign you need a code-signing certificate from a CA (OV or EV; EV gets SmartScreen trust immediately) or Azure Trusted Signing. With a `.pfx` and the Windows SDK's `signtool`:

    signtool sign /fd SHA256 /td SHA256 /tr http://timestamp.digicert.com /f cert.pfx /p <password> packaging\Output\Secretary-Setup-<version>.exe
    signtool verify /pa packaging\Output\Secretary-Setup-<version>.exe

Sign after the installer is built and before its SHA-256 is computed (the release workflow computes it from the file it finds, so sign inside the workflow before that step if you automate it, with the certificate and password as GitHub Actions secrets, never in the repo). A self-signed certificate does not remove the warning for other people.

## Demo GIF
1. Install ScreenToGif (free). Use a scratch data folder with made-up data so no real mail or names appear: `$env:SECRETARY_DATA_ROOT = "$env:TEMP\secretary-demo"; python -m secretary`.
2. Follow the README "Demo" steps; keep it under about 30 seconds and 10 MB.
3. Save as `docs/demo.gif`, add `![Demo](docs/demo.gif)` to the README, commit.

## Version, tag, publish
1. `python scripts/bump_version.py 0.2.0` (rewrites pyproject, `__init__.py`, `version_info.txt` and the installer default; `--check` shows them), run the tests, commit "release: 0.2.0".
2. Push the branch, open the PR, merge it to master.
3. First prove the workflow with a throwaway tag: `git tag v0.0.1-test; git push origin v0.0.1-test`. Watch Actions > Release. It must go green and create a draft Release with the installer and `.sha256`. Then delete the draft (Releases page) and the tag: `git push origin :refs/tags/v0.0.1-test; git tag -d v0.0.1-test`.
4. On master: `git tag v0.2.0; git push origin v0.2.0`. The workflow builds, runs `--diagnose` on the built exe, makes the installer and a **draft** Release.
5. Open the draft on GitHub, paste `docs/release_notes_draft.md`, check the two attachments, and press Publish. If the workflow fails: fix, delete the tag (`git push origin :refs/tags/v0.2.0`), retag.
