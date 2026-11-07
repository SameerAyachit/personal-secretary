"""FakeLLM contract run of the 40-case eval suite (plan §17.4, P0-03).

Runs every eval case against a FakeLLM pre-loaded with the expected tool call
(or no tool call for query / no-tool / ambiguous cases). All 40 must pass and
a report is written to docs/eval_results/. This is the contract run that CI
executes on every push; the live run against a real model is human-gated.
"""

from __future__ import annotations

import os

import pytest
from tests.eval.cases import CASES
from tests.eval.harness import normalise_tool_call, run_all, write_report

from secretary.llm.base import LLMResponse, ToolCall
from secretary.llm.fake import FakeLLM

REPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "eval_results")


def _fake_for(case):
    """Build a FakeLLM that returns this case's expected tool call (or none)."""
    fake = FakeLLM()
    if case.expected_tool is None:
        # Query / no-tool / ambiguous: the model returns no tool call.
        fake.add(LLMResponse(text="", tool_calls=[], usage={}, headers={}, model="fake"))
    else:
        fake.add(
            LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(call_id="call_1", name=case.expected_tool, args=dict(case.expected_args))
                ],
                usage={},
                headers={},
                model="fake",
            )
        )
    return fake


@pytest.mark.asyncio
async def test_fakellm_contract_all_cases_pass():
    os.makedirs(REPORT_DIR, exist_ok=True)
    results = []
    for case in CASES:
        fake = _fake_for(case)

        async def chat_fn(messages, tools, _fake=fake):
            resp = await _fake.chat(
                messages=messages or [],
                tools=tools,
                max_tokens=50,
                temperature=0.1,
                purpose="eval",
            )
            return normalise_tool_call(resp)

        results.extend(await run_all([case], chat_fn))

    report_path = os.path.join(REPORT_DIR, "2026-11-07_fakellm_contract.md")
    write_report(results, report_path, model="fake")

    failed = [r for r in results if not r.passed]
    assert not failed, f"{len(failed)} case(s) failed: " + ", ".join(r.case_id for r in failed)
    # Decision table (plan §7.9): FakeLLM contract is 100% → proceed as primary.
    assert all(r.passed for r in results)
