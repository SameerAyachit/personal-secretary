"""The 40 starter eval cases (plan §17.4).

Each case asserts the tool the agent should choose and the *words* it should
pass (``when_text`` / ``recurrence_text``), never resolved times. Categories
and counts match the plan's table: create task 6, reminder relative 6,
reminder absolute/day-first 6, recurring 4, query 6, no tool needed 6,
confirm-class action 3, ambiguous must-ask 3 = 40.

An eval case is run against an LLM client plus an agent hook; the case's
``check`` receives the normalised ``ToolCall`` (or None) and returns True if
the case passes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

ToolCheck = Callable[[dict | None], bool]


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    user_text: str
    expected_tool: str | None
    expected_args: dict
    check: ToolCheck | None = None
    must_ask: bool = False
    description: str = ""

    def passes(self, tool_call: dict | None) -> bool:
        if self.check is not None:
            return self.check(tool_call)
        if self.expected_tool is None:
            # No tool should be called (query / no-tool / ambiguous).
            return tool_call is None
        if tool_call is None:
            return False
        if tool_call.get("name") != self.expected_tool:
            return False
        args = tool_call.get("args", {}) or {}
        return all(args.get(key) == value for key, value in self.expected_args.items())


def _when(text: str) -> dict:
    return {"when_text": text}


def _recur(text: str) -> dict:
    return {"recurrence_text": text}


CASES: list[EvalCase] = [
    # ---- Create task (6) ----
    EvalCase(
        "create-1", "create task", "add a task to submit the lab report by Friday",
        "tasks_add", _when("by Friday"),
        description="Create a task with a relative weekday deadline.",
    ),
    EvalCase(
        "create-2", "create task", "create a task to call the dentist tomorrow",
        "tasks_add", _when("tomorrow"),
        description="Create a task due tomorrow.",
    ),
    EvalCase(
        "create-3", "create task", "add a task: buy groceries",
        "tasks_add", {},
        description="Create a task with no time.",
    ),
    EvalCase(
        "create-4", "create task", "task to submit the lab report due Friday 5pm",
        "tasks_add", _when("Friday 5pm"),
        description="Create a task with a specific due time.",
    ),
    EvalCase(
        "create-5", "create task", "add a task to review the contract next week",
        "tasks_add", _when("next week"),
        description="Create a task due next week.",
    ),
    EvalCase(
        "create-6", "create task", "create a task to file taxes by April 15",
        "tasks_add", _when("by April 15"),
        description="Create a task with a calendar-date deadline.",
    ),

    # ---- Reminder, relative (6) ----
    EvalCase(
        "rem-rel-1", "reminder relative", "remind me in 20 minutes to drink water",
        "reminders_add", _when("in 20 minutes"),
        description="Relative reminder in minutes.",
    ),
    EvalCase(
        "rem-rel-2", "reminder relative", "remind me in 1 hour to stand up",
        "reminders_add", _when("in 1 hour"),
        description="Relative reminder in hours.",
    ),
    EvalCase(
        "rem-rel-3", "reminder relative", "remind me in 30 seconds to save the file",
        "reminders_add", _when("in 30 seconds"),
        description="Relative reminder in seconds.",
    ),
    EvalCase(
        "rem-rel-4", "reminder relative", "remind me in half an hour to check the oven",
        "reminders_add", _when("in half an hour"),
        description="Relative reminder phrased as half an hour.",
    ),
    EvalCase(
        "rem-rel-5", "reminder relative", "remind me in 90 minutes to call back",
        "reminders_add", _when("in 90 minutes"),
        description="Relative reminder over an hour.",
    ),
    EvalCase(
        "rem-rel-6", "reminder relative", "remind me in 5 minutes to take a break",
        "reminders_add", _when("in 5 minutes"),
        description="Short relative reminder.",
    ),

    # ---- Reminder, absolute / day-first (6) ----
    EvalCase(
        "rem-abs-1", "reminder absolute/day-first", "remind me on 05/11 at 9am",
        "reminders_add", _when("05/11 at 9am"),
        description="Day-first date (5 November) at 9am.",
    ),
    EvalCase(
        "rem-abs-2", "reminder absolute/day-first", "remind me on 06/11 at 2pm",
        "reminders_add", _when("06/11 at 2pm"),
        description="Day-first date (6 November) at 2pm.",
    ),
    EvalCase(
        "rem-abs-3", "reminder absolute/day-first", "remind me tomorrow at 8am",
        "reminders_add", _when("tomorrow at 8am"),
        description="Relative day with absolute time.",
    ),
    EvalCase(
        "rem-abs-4", "reminder absolute/day-first", "remind me on 05/11",
        "reminders_add", _when("05/11"),
        description="Day-first date with no time.",
    ),
    EvalCase(
        "rem-abs-5", "reminder absolute/day-first", "remind me tonight at 9",
        "reminders_add", _when("tonight at 9"),
        description="Tonight phrase (plan §17.4).",
    ),
    EvalCase(
        "rem-abs-6", "reminder absolute/day-first", "remind me EOD to lock up",
        "reminders_add", _when("EOD"),
        description="End-of-day phrase (plan §17.4).",
    ),

    # ---- Recurring reminder (4) ----
    EvalCase(
        "recur-1", "recurring reminder", "every weekday at 8:30 remind me to check mail",
        "reminders_add", {"when_text": "every weekday at 8:30"},
        description="Weekday recurrence at a fixed time.",
    ),
    EvalCase(
        "recur-2", "recurring reminder", "every Monday remind me to review the backlog",
        "reminders_add", {"when_text": "every Monday"},
        description="Weekly recurrence on Monday.",
    ),
    EvalCase(
        "recur-3", "recurring reminder", "every day at 9pm remind me to brush teeth",
        "reminders_add", {"when_text": "every day at 9pm"},
        description="Daily recurrence at 9pm.",
    ),
    EvalCase(
        "recur-4", "recurring reminder", "the first of every month remind me to pay rent",
        "reminders_add", {"when_text": "the first of every month"},
        description="Monthly recurrence.",
    ),

    # ---- Query (6) ----
    EvalCase(
        "query-1", "query", "what's on my plate tomorrow", None, {},
        description="Calendar/plate query; no write tool.",
    ),
    EvalCase(
        "query-2", "query", "what tasks are due today", None, {},
        description="Task list query.",
    ),
    EvalCase(
        "query-3", "query", "when is my next reminder", None, {},
        description="Reminder lookup query.",
    ),
    EvalCase(
        "query-4", "query", "show me my calendar for Friday", None, {},
        description="Calendar read query.",
    ),
    EvalCase(
        "query-5", "query", "do I have any overdue tasks", None, {},
        description="Overdue task query.",
    ),
    EvalCase(
        "query-6", "query", "what meetings do I have next week", None, {},
        description="Meeting lookup query.",
    ),

    # ---- No tool needed (6) ----
    EvalCase(
        "none-1", "no tool needed", "thanks", None, {},
        description="Small talk; no tool.",
    ),
    EvalCase(
        "none-2", "no tool needed", "hello", None, {},
        description="Greeting; no tool.",
    ),
    EvalCase(
        "none-3", "no tool needed", "what does FTS5 stand for", None, {},
        description="General knowledge question; no tool.",
    ),
    EvalCase(
        "none-4", "no tool needed", "how do I set a reminder", None, {},
        description="Help question; no tool.",
    ),
    EvalCase(
        "none-5", "no tool needed", "great, that worked", None, {},
        description="Acknowledgment; no tool.",
    ),
    EvalCase(
        "none-6", "no tool needed", "can you help me", None, {},
        description="Open help offer; no tool.",
    ),

    # ---- Confirm-class action (3) (class C → pending_actions) ----
    EvalCase(
        "confirm-1", "confirm-class action", "send the draft to Ravi",
        "email_send", {"to": "Ravi"},
        description="Sending email is class C; prepare for approval, do not send.",
    ),
    EvalCase(
        "confirm-2", "confirm-class action", "delete all my completed tasks",
        "tasks_bulk_delete", {},
        description="Bulk delete is class C; prepare for approval.",
    ),
    EvalCase(
        "confirm-3", "confirm-class action", "invite Sarah to the meeting",
        "event_invite", {"attendee": "Sarah"},
        description="Inviting attendees is class C; prepare for approval.",
    ),

    # ---- Ambiguous, must ask (3) ----
    EvalCase(
        "ambig-1", "ambiguous must ask", "remind me about the thing", None, {},
        must_ask=True,
        description="Ambiguous item; agent must ask one question, call no tool.",
    ),
    EvalCase(
        "ambig-2", "ambiguous must ask", "delete that task", None, {},
        must_ask=True,
        description="Ambiguous reference; agent must ask which task.",
    ),
    EvalCase(
        "ambig-3", "ambiguous must ask", "remind me at 5", None, {},
        must_ask=True,
        description="Missing what to remind about; agent must ask.",
    ),
]

assert len(CASES) == 40, f"expected 40 cases, got {len(CASES)}"

# Category counts match the plan table.
from collections import Counter  # noqa: E402  (module-level sanity check)

_COUNTS = Counter(c.category for c in CASES)
assert _COUNTS["create task"] == 6
assert _COUNTS["reminder relative"] == 6
assert _COUNTS["reminder absolute/day-first"] == 6
assert _COUNTS["recurring reminder"] == 4
assert _COUNTS["query"] == 6
assert _COUNTS["no tool needed"] == 6
assert _COUNTS["confirm-class action"] == 3
assert _COUNTS["ambiguous must ask"] == 3
