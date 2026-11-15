# Live eval runbook (human-run; needs your NVIDIA key)

Purpose: measure how reliably the configured model picks the right tool with the right
words, then choose the runtime model and its settings (plan 7.9). The FakeLLM contract run
(`pytest tests/eval`) only proves the harness; this run tests the real model.

## Run
1. Settings > AI: provider NVIDIA, pick the model, save your key (Credential Manager).
2. From the project root, with the venv active:
   `python -m tests.eval.live` (all 42 cases, 2 s apart, about 2 minutes), or
   `python -m tests.eval.live --only create-1,query-2,event-recur-1` for a few.
3. The report is written to `docs/eval_results/<date>_<model>.md`.

What leaves your machine: only the 42 case sentences (for example "remind me in 20 minutes
to drink water"), the app's system prompt and the tool schemas, to the provider you chose.
No tasks, mail or calendar data. NVIDIA trial terms may record inputs/outputs (PRIVACY.md).
The key is read from Credential Manager and never printed or logged.

## Read the result (plan 7.9)
| Pass rate | Action |
|---|---|
| 90% or more | Keep this model as primary. |
| 80-89% | Keep as primary; list the failing categories below and fix prompts/tool descriptions first. |
| under 80% | Try `llm.thinking = true`, then another model for write tools only. |

## What to change for each kind of failure (Settings or config.toml)
- Wrong or missing tool in `create task` / `reminder` / `recurring event`: improve the tool
  description or the system prompt in `agent/loop.py`, re-run; try `llm.temperature_tools = 0`.
- Wrote a time itself instead of the user's words (`when_text`): same fix, plus a new case.
- `query` cases answering without a list tool: the guard in `agent/loop.py` catches this in
  the app, but a high miss rate means the model needs `llm.thinking = true`.
- Slow (median latency in the report over about 8 s): `llm.thinking = false`, smaller model.

Record the chosen model and rate in `docs/decisions_log.md` and add a dated ADR if the
default model changes. Do not change defaults before you have a report.
