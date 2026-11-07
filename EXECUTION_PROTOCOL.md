# EXECUTION PROTOCOL — Secretary build

Binding on the coding agent. This file lives in the project root `D:\secretary agent\` next to the plan.
The spec is `personal_secretary_agent_master_plan.md` in the same root folder (the user's plan, never edited, never moved, never renamed). Below it is called "the plan".
If this protocol and the plan conflict, the PLAN wins on WHAT to build; this protocol wins on HOW to work.

---

## 0. Prime rules (re-read after every context reset)

1. Build only what the plan says. No extra features, screens, packages, layers, or "improvements". Plan §1.2 non-goals are forbidden.
2. Where the plan is silent or says "decide when you reach it" (§22.1): pick the simplest option consistent with the plan, append one line to `docs/decisions_log.md` (`date | task | decision | why`), continue. Do not ask the human.
3. Never write "done", "works", or "passes" unless you ran the command in THIS session and saw it pass. Record the last ~15 lines of real output in `docs/progress.md`.
4. Never read the whole plan. Read only the line ranges the current task needs (Section Map below). Max 400 lines per read.
5. One task = one small unit (one module or one function + its tests). Never "build Phase N" in one step.
6. Tests first for logic (time, recurrence, limiter, migrations, safety classes, normalize_response). Write the failing test, see it fail, implement, see it pass.
7. Never invent an API. Before using any Qt/PySide6, desktop-notifier, dateparser, Google, httpx, keyring, tiktoken, trafilatura, ddgs, or pyinstaller call: look it up with the docs MCP (Context7) if available; otherwise introspect the installed package (`python -c "import X, inspect; print(inspect.signature(X.f))"`, `help()`, `pip show`). If neither works, write a 5-line probe script and run it. Never guess a signature.
8. Layering (plan §3.2) is law: `ui → controller → agent → tools → store/integrations`. All SQL only in `src/secretary/store/`. Never touch widgets off the main thread. `lint-imports` must pass.
9. Never add a dependency outside plan §4.1. If one is truly unavoidable: add a row to `docs/deps.md` with the reason, add a line to `docs/human_todo.md`, then continue.
10. Secrets only through `keyring`. Never print, log, commit, or write an API key anywhere.

## 1. Safety boundaries

- The project root (repo root) is `D:\secretary agent\` (the path contains a space: always quote it in commands, e.g. `cd "D:\secretary agent"`). Do NOT create a nested `secretary/` folder for the repo: the plan's layout (§4.2) starts at this root, so `src/`, `migrations/`, `tests/`, `docs/`, `packaging/`, `spikes/` go directly inside it. The Python package is `src/secretary/`.
- Never edit, move, rename, or delete `personal_secretary_agent_master_plan.md` or `EXECUTION_PROTOCOL.md`. Both stay in the root. Add `.venv/`, `build/`, `dist/`, `credentials.json`, `__pycache__/` and `*.db` to `.gitignore`.
- Work only inside the project directory. Never create, edit, or delete files outside it (exception: installs into the project venv `.venv` inside the root).
- Never run: `git push`, `git push --force`, `git reset --hard` on commits you did not make, `rm -rf` / `Remove-Item -Recurse` outside `build/` `dist/` `__pycache__` `.pytest_cache`, registry edits outside HKCU `Run` key code paths executed by tests with a temp key, or anything needing admin rights.
- Never apply a migration that was already committed; add a new numbered file (plan §5.2).
- Never touch the user's real `%LOCALAPPDATA%\Secretary` during tests: tests use a temp data root injected through `paths.py`.
- Network use is limited to package installs and documentation lookups, except the optional live LLM probe/eval (§4 below).

## 2. Section map of the plan (line ranges)

| § | Topic | Lines |
|---|---|---|
| 1 | Product, non-goals, MVP demo, metrics | 41-80 |
| 2 | ADR table D1-D15 | 81-104 |
| 3 | Architecture, threads, layering, flows | 105-191 |
| 4 | Stack, repo layout | 192-267 |
| 5 | Data model, migrations, backup | 268-480 |
| 6 | Config, secrets, first-run wizard | 481-515 |
| 7 | LLM layer, limiter, routing, quirks | 516-624 |
| 8 | Agent loop, tools, safety classes, injection defence | 625-713 |
| 9 | Time, dates, recurrence | 714-765 |
| 10 | Scheduler, inbox, catch-up | 766-805 |
| 11 | Notifications | 806-826 |
| 12 | UI/UX | 827-862 |
| 13 | Google Calendar and Gmail | 863-892 |
| 14 | Search and research | 893-923 |
| 15 | Security and privacy | 924-948 |
| 16 | Reliability, logging | 949-972 |
| 17 | Testing, eval suite | 973-1021 |
| 18 | Packaging, installer, release | 1022-1046 |
| 19 | opencode setup (AGENTS.md, skills, commands, agents, MCP) | 1047-1157 |
| 20 | Concern catalogue C-1..C-64 | 1158-1259 |
| 21 | Phased task list with acceptance | 1260-1330 |
| 22 | Open items, cut ladder, definition of done | 1331-1364 |
| 23 | Appendices A-H (config, system prompt, checklists) | 1365-1498 |

Always paste exact code/SQL from the plan where it exists (migration runner §5.2, schema §5.3, limiter §7.4, loop §8.1, Appendix A config, Appendix B system prompt). Copy, then adapt only to make it run.

## 2b. Pre-flight (do once, before any code)

Run and record results in `docs/progress.md`:
1. OS and shell (`python -c "import platform;print(platform.platform())"`). Use `python -m ...` forms and `pathlib`; no bash-only syntax if the shell is PowerShell.
2. `python --version` must be 3.12.x (else install/pin via `uv` if present; else record in human_todo and continue with the closest 3.12+).
3. `git --version`; `git init` if needed.
4. Which MCP/doc lookup is available (Context7 yes/no).
5. The target is Windows and `D:\secretary agent` is a Windows path, so expect Windows. If the OS is NOT Windows: Windows-only code (`winreg`, Credential Manager backend, toasts, PyInstaller `.exe`, Inno Setup) MUST sit behind small interfaces with import guards, be covered by tests using fakes, and be marked `HUMAN-GATED` (see §4). The rest of the app MUST still run and test headless.
6. GUI tests: set `QT_QPA_PLATFORM=offscreen` in pytest config so pytest-qt runs without a display.
7. Verify the plan exists at the root and has 1498 lines (PowerShell: `(Get-Content "personal_secretary_agent_master_plan.md").Count`). Create a `.venv` in the root (`python -m venv .venv`, or `uv venv`) and run everything inside it. Create `docs/` if missing.

## 3. Task loop (run for EVERY task ID in plan §21, in order)

```
A. READ     task row in §21 (use the line ranges) + only the sections it cites + related concerns in §20.
B. CARD     write in docs/progress.md: task ID, files to create/edit, acceptance (copied from §21), tests to write first.
C. TEST     write tests; run them; confirm they fail for the right reason.
D. BUILD    implement the minimum that satisfies the acceptance. Files < 300 lines; functions small; type hints; pydantic for external data; logging not print.
E. VERIFY   run, in order:  ruff check .   |   python -m pytest -q   |   lint-imports
            (mypy is lenient: run it, fix only real errors).
E2. UI TASKS ONLY (anything under src/secretary/ui/): first load `.opencode/skills/secretary-ui-design/SKILL.md` and follow it, including its screenshot review loop and "UI task done" definition.
F. FIX      on failure: fix and re-run. Max 3 fix cycles per failing item. If an edit tool fails twice on a file, rewrite the whole file.
G. RECORD   append result lines to docs/progress.md; mark the task DONE / DONE-HUMAN-GATED / BLOCKED.
H. COMMIT   git add -A && git commit -m "feat(scope): message" (conventional commits). Commit only when E is green.
I. NEXT     start the next task with a clean mental slate; do not re-open finished code unless a test demands it.
```

Task status vocabulary (only these):
- `DONE` — acceptance met, E green, evidence recorded.
- `DONE-HUMAN-GATED` — code and tests complete with fakes; the real-world check needs the human (listed in `docs/human_todo.md`).
- `BLOCKED` — 3 fix cycles failed. Write cause, what you tried, and the smallest next step to `docs/blockers.md`. Continue with any task that does not depend on it; if all remaining tasks depend on it, STOP (§6).

## 4. Human-gated items (never fake, never skip silently)

Build everything possible with fakes/mocks, mark the real check, and append to `docs/human_todo.md` with exact steps for the human:

| Item | What you build | What the human must do |
|---|---|---|
| P0-02 live LLM probe | `llm/probe.py`, `spikes/probe_llm.py`, config, ADR skeleton | Put a key in Credential Manager (or env `SECRETARY_PROBE_KEY` for the probe only), run the probe, paste the limits into `docs/groq_limits_<date>.md` |
| P0-03 / P1-09 live eval | Harness (40 cases), FakeLLM contract run (this you DO run), live-run command | Run the live eval with a real key; choose the model by plan §7.9 |
| P0-05 / P2-09 clean-profile install, toast from installed exe, reboot autostart | PyInstaller spec, Inno `installer.iss`, `--diagnose`, Run-key code with temp-key tests | Install on a clean Windows user/VM and run the manual script |
| P0-06 / Phase 3 / 3.5 real Google OAuth | auth, calendar, gmail code against mocked HTTP (`respx`) | Create the Google Cloud project, "In production", place `credentials.json` |
| 7-day soak test, demo video, screenshots, code signing, GitHub Release, CI run | Workflows, scripts, docs templates | Do them |
| Stronger-model review (plan §19.1, `/review-phase`) | The review command + checklist | Optionally run it with a stronger model |

If a live LLM key is already available in Credential Manager/env at run time, you MAY run live probes/evals; otherwise do not try.

## 5. Phase order and gates

Execute plan §21 exactly: **Phase 0 → 1 → 2 → 3 → 3.5 → 4 → 5 → 6**, task IDs in table order. Ignore the day estimates.

Phase 0 specifics: P0-01 first. Create everything plan §19 lists, PLUS keep the human-supplied skill `.opencode/skills/secretary-ui-design/SKILL.md` exactly as it is (never overwrite or delete it; it counts as a sixth project skill and implements plan §12). Also create: `AGENTS.md` (use the plan's draft §19.2, but change its "Source of truth" line to point to `personal_secretary_agent_master_plan.md` in the root, and add one line: "Work procedure: follow EXECUTION_PROTOCOL.md in the root." Log this one adaptation in `docs/decisions_log.md`; it exists only because the plan file lives in the root, not in `docs/`), the five skills of §19.3, the six commands (§19.4), three agents (§19.5), `opencode.json` MCP config (§19.6; Context7 only if the human has not set others), ADR-001 recording D1-D15, `docs/progress.md`, `docs/deps.md`, `docs/human_todo.md`, `docs/blockers.md`, `docs/decisions_log.md`.

Phase gate (before moving to the next phase) — run plan §21 "Phase exit checklist" and record each line:
- [ ] ruff, mypy, pytest, lint-imports green (paste results)
- [ ] `python -m secretary --diagnose` passes (once it exists)
- [ ] Packaging smoke builds where the OS allows (else HUMAN-GATED)
- [ ] Eval re-run against FakeLLM if prompts/tools changed; report in `docs/eval_results/`
- [ ] CHANGELOG, ADRs, progress.md current
- [ ] Self-review (below) done; findings fixed or logged

Self-review (replaces the stronger-model reviewer; takes one pass, read-only):
1. `grep` that `ui/` never imports `store`, `store` never imports `agent`/`ui`.
2. Every Qt widget mutation happens in the main thread (search for widget calls inside worker/scheduler code).
3. Every class C path goes through `pending_actions` with a code-built summary; untrusted text only reaches tool-less LLM calls.
4. No tool accepts an absolute timestamp from the LLM; no `datetime.now()` outside the clock module.
5. No secrets in logs/config/DB (grep for key patterns; redaction filter test exists).
6. Every plan concern relevant to this phase (§20) is handled or noted in `docs/progress.md`.
7. Every new function with logic has a test.

## 6. STOP conditions (the only times you address the human)

Stop and write a short message (what is done, what stopped you, the one decision/action needed) ONLY if:
- a task is BLOCKED and every remaining task depends on it;
- the plan and the environment are fundamentally incompatible (for example Python 3.12 or PySide6 cannot be installed at all);
- you would have to break a Prime rule or Safety boundary to proceed;
- a command would be destructive or run outside the project directory.

Everything else: decide, log, continue.

## 7. Context hygiene (hard limits for 200K-context models; sensible for 1M too)

- Never load the whole plan, never `cat` large files, never print full test logs: use `-q`, `| tail -n 20` (PowerShell: `| Select-Object -Last 20`).
- At the start of every session and after any context reset/compaction: read, in this order, `AGENTS.md`, `EXECUTION_PROTOCOL.md` (root) §0-§3, `docs/progress.md` (last 60 lines). Then resume at the first task not marked DONE / DONE-HUMAN-GATED.
- After every task, `docs/progress.md` must be enough to resume: current phase, last task, next task, open blockers.
- Keep `docs/progress.md` compact: one line per finished task; keep full detail only for the current task. Move older detail to `docs/progress_archive.md`.
- If you notice yourself forgetting earlier decisions or repeating failed edits, stop, update `docs/progress.md`, and say: "Context is getting full. Start a fresh session and send: Continue the build per EXECUTION_PROTOCOL.md in the project root."
- If a model's tool-edits keep failing (3 consecutive on the same file), rewrite the file fully instead of patching.

## 8. Windows pitfalls checklist (apply while coding; see also plan §20.5)

- Open files with `encoding="utf-8"`; use `pathlib`; no hardcoded `C:\` paths (`paths.py` only).
- `tzdata` must be installed for `zoneinfo`.
- Never `asyncio.run()` on the main thread; agent worker owns its loop (plan §3.1).
- SQLite: pragmas from §5.4; one writer behind an `RLock`.
- PyInstaller: include `tzdata`, the vendored tiktoken encoding file, `migrations/`, and QSS/theme assets as data files; test the built exe path, not only dev.
- Toasts need an AUMID shortcut; test failure of the notifier leaves the inbox and popup intact (plan §11.2).

## 9. Final deliverable

When all tasks are processed, write `docs/BUILD_REPORT.md`:
1. Table: every task ID → status (DONE / DONE-HUMAN-GATED / BLOCKED) → evidence (command + result line).
2. Plan §22.4 Definition of done: each line → met / needs human / not met, with the reason.
3. Plan §20 catalogue: each C-ID → handled (where in code/tests) / deferred (why).
4. Copy of `docs/human_todo.md` ordered by what unblocks most.
5. How to run: `python -m secretary`, run tests, build the installer.
6. Final `git log --oneline | head -20`.

Then print a 10-line summary to the human. Do not claim v1.0 complete if any plan §22.4 line is "not met".
