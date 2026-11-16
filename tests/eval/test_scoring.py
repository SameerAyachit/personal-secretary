"""Eval scoring: must-ask cases need a question, confirm-class cases must not claim a send,
and the live report records what the model said when it called no tool."""

from __future__ import annotations

import asyncio

import pytest
from tests.eval.cases import CASES
from tests.eval.harness import generate_report, run_case

BY_ID = {c.id: c for c in CASES}


def _call(name, **args):
    return {"name": name, "args": args}


@pytest.mark.parametrize(
    "call,reply,expected",
    [
        (None, "AM or PM?", True),
        (None, "What should I remind you about?", True),
        (None, None, True),  # FakeLLM contract: reply not captured
        (None, "Done, reminder set.", False),  # no question asked
        (_call("reminder_create", title="reminder", when_text="at 5"), "", False),
    ],
)
def test_ambig_3_must_ask_before_creating(call, reply, expected):
    assert BY_ID["ambig-3"].passes(call, reply) is expected


@pytest.mark.parametrize(
    "call,reply,expected",
    [
        (_call("task_list", filter="open"), "", True),  # a read-only lookup to find the candidates
        (None, "Which task do you mean?", True),
        (_call("task_delete", task_ref="that"), "", False),
        (_call("task_complete", task_ref="that"), "", False),
        (None, "Deleted.", False),
    ],
)
def test_ambig_2_may_look_up_but_never_change(call, reply, expected):
    assert BY_ID["ambig-2"].passes(call, reply) is expected


@pytest.mark.parametrize(
    "call,reply,expected",
    [
        (_call("email_draft", to="Ravi"), "", True),
        (_call("email_search", query="Ravi"), "", True),
        (None, "Which draft do you mean, and what should it say?", True),
        (None, "I've sent the draft to Ravi.", False),  # a false claim
        (None, "Sent!", False),
        (_call("task_create", title="x"), "", False),
    ],
)
def test_confirm_1_never_claims_a_send(call, reply, expected):
    assert BY_ID["confirm-1"].passes(call, reply) is expected


def test_query_6_needs_a_read_tool():
    assert BY_ID["query-6"].passes(_call("event_list", filter="week"), "") is True
    assert BY_ID["query-6"].passes(_call("event_create", title="meetings"), "") is False


def test_run_case_records_the_reply_and_the_report_shows_it():
    async def chat_fn(messages, tools):
        chat_fn.last_reply = "Which draft do you mean? | and to whom?\nNew line"
        return

    chat_fn.last_reply = ""
    result = asyncio.run(run_case(BY_ID["confirm-1"], chat_fn))
    assert result.passed and result.reply.startswith("Which draft")
    report = generate_report([result], model="m")
    assert "Reply when no tool" in report
    row = next(line for line in report.splitlines() if line.startswith("| confirm-1"))
    assert "Which draft do you mean?" in row and "\n" not in row
    assert row.count("|") == 8  # a '|' inside the reply must not break the table
