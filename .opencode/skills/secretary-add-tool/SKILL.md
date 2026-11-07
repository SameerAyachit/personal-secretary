---
name: secretary-add-tool
description: Use when adding or changing an agent tool. Covers pydantic schema, safety class, routing, `when_text` rule, FakeLLM test, eval cases, prompt version bump.
---
1. Define a pydantic model: ≤5 args, enums where possible, time args are `*_text` strings (never absolute timestamps from the LLM).
2. Choose safety class (A read, B reversible write, C consequential). Class C must use `pending_actions` with a code-built summary.
3. Register in `tools/registry.py` with a group name; add routing keywords in `agent/router.py`.
4. Write a FakeLLM integration test and ≥3 eval cases (include one ambiguous case).
5. Bump `PROMPT_VERSION` if the tool description changes. Run the eval harness against FakeLLM.
6. Run `ruff check`, `pytest -q`, `lint-imports`.
