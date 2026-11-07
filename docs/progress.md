# Build progress

## Pre-flight (protocol §2b) — recorded
- OS: Windows-11-10.0.26200-SP0 (Windows target confirmed)
- Python: 3.12.10 (matches plan pin) — running inside `.venv`
- git: 2.55.0.windows.3 (init done)
- Context7: available; library ID `/websites/doc_qt_io_qtforpython-6` (PySide6 docs)
- Plan: 1498 lines confirmed at root
- `.venv` created in root; runtime + test + quality deps installed (PySide6, httpx, dateparser, python-dateutil, tzdata, tiktoken, keyring, desktop-notifier, pydantic, ddgs, trafilatura, pytest, pytest-qt, pytest-asyncio, respx, time-machine, hypothesis, ruff, mypy, import-linter, pre-commit)
- QT_QPA_PLATFORM=offscreen to be set in pytest config (pyproject.toml)

## Phase 0 (plan §19) — in progress
P0-01 skeleton: AGENTS.md ✓, 5 skills ✓, 6 commands ✓, 3 agents ✓, opencode.json ✓, ADR-001 ✓, docs/deps.md ✓, docs/human_todo.md ✓, docs/blockers.md ✓, docs/decisions_log.md ✓, `.opencode/skills/secretary-ui-design/SKILL.md` kept ✓ (human-supplied, untouched). src/secretary package stubs + .github/workflows/ci.yml + importlinter.toml.
P0-01 acceptance (ruff, pytest, lint-imports on empty package): ruff ✓, pytest ✓, lint-imports ✓ (7 kept, 0 broken). DONE — committed.

P0-02 LLM probe + provider decision: built llm/base.py, llm/errors.py, llm/openai_compat.py, llm/fake.py, llm/probe.py. Tests (9) pass, ruff green, lint-imports green. Live probe run needs a real Groq key → DONE-HUMAN-GATED (see docs/human_todo.md P0-02). Probe writes docs/groq_limits_<date>.md; ADR to be recorded by human after probe.

Next: P0-03 eval harness (FakeLLM contract — this part is runnable by agent; live run human-gated).

P0-03 eval harness + 40 cases + FakeLLM contract: tests/eval/{__init__,cases,harness,test_contract}. Report generated at docs/eval_results/2026-11-07_fakellm_contract.md (100% pass). ruff ✓, pytest ✓, lint-imports ✓. Live run against a real model needs a key → DONE-HUMAN-GATED (docs/human_todo.md P0-03/P1-09).

Next: P0-04 Qt shell spike (tray, window hide/show, single-instance, worker+asyncio, hotkey, popup card) — UI task, follows secretary-ui-design skill.


