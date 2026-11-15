# Human TODO

Real-world checks that need a key, a clean Windows profile, Google credentials, or a manual action. Code is built with fakes first; these steps verify the real thing. Never fake a real-world result.

Order (what unblocks most first):

1. P0-02 live LLM probe — put an NVIDIA key in Credential Manager (or env `SECRETARY_PROBE_KEY` for the probe only), run `python -m secretary.llm.probe`, paste limits into `docs/nvidia_limits_<date>.md`, record ADR.
2. P0-03 / P1-09 live eval — run the eval harness with a real key; choose the model per plan §7.9; FakeLLM contract run is done by the agent.
3. P0-05 / P2-09 clean-profile install — install PyInstaller one-folder app + Inno installer on a clean Windows user/VM; confirm toast from packaged exe with AUMID shortcut; confirm Run-key autostart; run `--diagnose`.
4. P0-06 / Phase 3 / 3.5 real Google OAuth — create Google Cloud project, set "In production", place `credentials.json`; test refresh flow and `invalid_grant`/Reconnect path.
5. 7-day soak test, demo video, screenshots, code signing, GitHub Release — per plan §22.4.

Each item is HUMAN-GATED; the app must work without the LLM and without Google credentials.

6. UI screenshots — eyeball docs/screenshots/settings_light_100.png, settings_dark_100.png,
   approvals_empty_light_100.png, approvals_empty_dark_100.png, approvals_with_item_light_100.png,
   approvals_with_item_dark_100.png against the secretary-ui-design checklist at 100% and
   150% scaling (regenerate 150% with QT_SCALE_FACTOR=1.5).

## Before the first public release (added 2026-11-15)

7. Run the live eval: `python -m tests.eval.live` (runbook: `docs/eval_runbook.md`); share the summary so model settings can be tuned.
8. Check and delete `%LOCALAPPDATA%\Secretary\google_token.json` (plaintext leftover; the app no longer uses it) and the stale `llm_api_key:groq` / `llm_api_key:gemini` Credential Manager entries if you do not use them.
9. Re-set any chat-made reminders or events created before the absolute-time fix (`python scripts/check_utc_bug.py` lists candidates).
10. Run the A2-A6 checks, then the 7-day soak on a clean profile.
11. Record `docs/demo.gif` (script in the README "Demo" section).
12. Sign the installer if you want to avoid SmartScreen warnings.
13. Bump the version (README "Building and releasing"), push the tag, review the draft Release and publish it. Edit the repository name in `[updates] repo` only if it differs from `SameerAyachit/personal-secretary`.
14. Check the first GitHub Actions run of `ci.yml` (mypy scope and the `pip-audit` job could not be run locally) and `release.yml` on a throwaway tag.
