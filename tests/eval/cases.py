"""Eval cases (plan §17.4): which real tool should the model pick, with which *words*.

Cases assert the tool the agent should choose and the words it should pass in
``when_text`` / ``recurrence_text``, never resolved times. Tool names are the real
registry names (``secretary.agent.wiring``). Categories (plan table): create task 6,
reminder relative 6, reminder absolute/day-first 6, recurring reminder 4, query 6,
no tool needed 6, confirm-class action 3, ambiguous must-ask 3, plus recurring event 2.

``expected_tool`` / ``expected_args`` are one example of a passing call (the FakeLLM
contract replays it); ``check`` is the real acceptance test, tolerant of the harmless
rewordings a live model produces.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

# (tool call or None, reply text or None when the runner does not capture text) -> pass?
ToolCheck = Callable[[dict | None, str | None], bool]


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

    def passes(self, tool_call: dict | None, reply: str | None = None) -> bool:
        if self.check is not None:
            return self.check(tool_call, reply)
        if self.expected_tool is None:
            return tool_call is None  # no tool: query-free chat or a question back
        if tool_call is None or tool_call.get("name") != self.expected_tool:
            return False
        args = tool_call.get("args", {}) or {}
        return all(str(args.get(k, "")).lower() == str(v).lower() for k, v in self.expected_args.items())


def _arg(call: dict | None, key: str) -> str:
    return str(((call or {}).get("args") or {}).get(key) or "").lower()


def _tool(*names: str, **needles: tuple[str, ...]) -> ToolCheck:
    """A call to one of ``names`` whose args contain (any of) the given words."""

    def check(call: dict | None, reply: str | None = None) -> bool:
        if call is None or call.get("name") not in names:
            return False
        return all(any(w in _arg(call, key) for w in words) for key, words in needles.items())

    return check


def _not_tool(*banned: str) -> ToolCheck:
    """Anything except the banned tools (asking a question or listing is fine)."""

    def check(call: dict | None, reply: str | None = None) -> bool:
        return call is None or call.get("name") not in banned

    return check


def _is_question(reply: str | None) -> bool:
    """A reply that asks something. ``None`` means the runner did not capture text (FakeLLM)."""
    return reply is None or "?" in reply


_SENT_CLAIM = re.compile(
    r"\b(?:i(?:'ve| have)?|already|just)\s+(?:sent|emailed)\b"
    r"|\b(?:has|have|was|been|is)\s+(?:been\s+)?sent\b|^\s*sent\b",
    re.IGNORECASE,
)


def _asks_no_tool(call: dict | None, reply: str | None = None) -> bool:
    """The agent must ask one question and call no tool."""
    return call is None and _is_question(reply)


def _lookup_or_ask(*lookups: str) -> ToolCheck:
    """Ask a question, or make a read-only lookup to find the candidates; never change anything."""

    def check(call: dict | None, reply: str | None = None) -> bool:
        if call is None:
            return _is_question(reply)
        return call.get("name") in lookups

    return check


def _prepare_or_ask(*names: str) -> ToolCheck:
    """Class C (send): draft/look up, or ask a question; never claim it was sent."""
    tool = _tool(*names)

    def check(call: dict | None, reply: str | None = None) -> bool:
        if call is not None:
            return tool(call, reply)
        return _is_question(reply) and not (reply and _SENT_CLAIM.search(reply))

    return check


def _case(cid, category, text, tool, args, check=None, must_ask=False, description=""):
    return EvalCase(cid, category, text, tool, args, check, must_ask, description)


def _make_task(cid, text, when, example):
    needles = {"when_text": when} if when else {}
    return _case(cid, "create task", text, "task_create", example, _tool("task_create", **needles),
                 description="Create a task; the due time goes in when_text as the user's words.")


def _make_rem(cid, category, text, when, example):
    return _case(cid, category, text, "reminder_create", example,
                 _tool("reminder_create", when_text=when), description="One-off reminder; words in when_text.")


def _make_recur(cid, text, rec, example):
    return _case(cid, "recurring reminder", text, "reminder_create", example,
                 _tool("reminder_create", recurrence_text=rec),
                 description="Repeating reminder; the rule goes in recurrence_text.")


def _make_query(cid, text, tools, example):
    return _case(cid, "query", text, tools[0], example, _tool(*tools),
                 description="Read question: call the matching list tool, never invent an answer.")


CASES: list[EvalCase] = [
    # ---- Create task (6) ----
    _make_task("create-1", "add a task to submit the lab report by Friday", ("friday",),
               {"title": "submit the lab report", "when_text": "Friday"}),
    _make_task("create-2", "create a task to call the dentist tomorrow", ("tomorrow",),
               {"title": "call the dentist", "when_text": "tomorrow"}),
    _make_task("create-3", "add a task: buy groceries", (), {"title": "buy groceries"}),
    _make_task("create-4", "task to submit the lab report due Friday 5pm", ("friday",),
               {"title": "submit the lab report", "when_text": "Friday 5pm"}),
    _make_task("create-5", "add a task to review the contract next week", ("next week",),
               {"title": "review the contract", "when_text": "next week"}),
    _make_task("create-6", "create a task to file taxes by April 15", ("april", "15/04", "04-15"),
               {"title": "file taxes", "when_text": "April 15"}),

    # ---- Reminder, relative (6) ----
    _make_rem("rem-rel-1", "reminder relative", "remind me in 20 minutes to drink water", ("20 min",),
              {"title": "drink water", "when_text": "in 20 minutes"}),
    _make_rem("rem-rel-2", "reminder relative", "remind me in 1 hour to stand up", ("1 hour", "an hour", "60 min"),
              {"title": "stand up", "when_text": "in 1 hour"}),
    _make_rem("rem-rel-3", "reminder relative", "remind me in 30 seconds to save the file", ("30 sec", "half a minute"),
              {"title": "save the file", "when_text": "in 30 seconds"}),
    _make_rem("rem-rel-4", "reminder relative", "remind me in half an hour to check the oven",
              ("half an hour", "30 min"), {"title": "check the oven", "when_text": "in half an hour"}),
    _make_rem("rem-rel-5", "reminder relative", "remind me in 90 minutes to call back", ("90 min", "1.5 hour"),
              {"title": "call back", "when_text": "in 90 minutes"}),
    _make_rem("rem-rel-6", "reminder relative", "remind me in 5 minutes to take a break", ("5 min",),
              {"title": "take a break", "when_text": "in 5 minutes"}),

    # ---- Reminder, absolute / day-first (6) ----
    _make_rem("rem-abs-1", "reminder absolute/day-first", "remind me on 05/11 at 9am", ("05/11",),
              {"title": "reminder", "when_text": "05/11 at 9am"}),
    _make_rem("rem-abs-2", "reminder absolute/day-first", "remind me on 06/11 at 2pm", ("06/11",),
              {"title": "reminder", "when_text": "06/11 at 2pm"}),
    _make_rem("rem-abs-3", "reminder absolute/day-first", "remind me tomorrow at 8am", ("tomorrow",),
              {"title": "reminder", "when_text": "tomorrow at 8am"}),
    _make_rem("rem-abs-4", "reminder absolute/day-first", "remind me on 05/11", ("05/11",),
              {"title": "reminder", "when_text": "05/11"}),
    _make_rem("rem-abs-5", "reminder absolute/day-first", "remind me tonight at 9", ("tonight", "9"),
              {"title": "reminder", "when_text": "tonight at 9"}),
    _make_rem("rem-abs-6", "reminder absolute/day-first", "remind me EOD to lock up", ("eod", "end of day"),
              {"title": "lock up", "when_text": "EOD"}),

    # ---- Recurring reminder (4) ----
    _make_recur("recur-1", "every weekday at 8:30 remind me to check mail", ("weekday",),
                {"title": "check mail", "when_text": "8:30", "recurrence_text": "every weekday at 8:30"}),
    _make_recur("recur-2", "every Monday remind me to review the backlog", ("monday",),
                {"title": "review the backlog", "when_text": "next Monday", "recurrence_text": "every Monday"}),
    _make_recur("recur-3", "every day at 9pm remind me to brush teeth", ("day",),
                {"title": "brush teeth", "when_text": "9pm", "recurrence_text": "every day at 9pm"}),
    _make_recur("recur-4", "the first of every month remind me to pay rent", ("month", "first"),
                {"title": "pay rent", "when_text": "1st", "recurrence_text": "the first of every month"}),

    # ---- Query (6): must call the real read tool ----
    _make_query("query-1", "what's on my plate tomorrow", ("event_list", "task_list", "plan_day"),
                {"filter": "tomorrow"}),
    _make_query("query-2", "what tasks are due today", ("task_list",), {"filter": "today"}),
    _make_query("query-3", "when is my next reminder", ("reminder_list",), {"filter": "open"}),
    _make_query("query-4", "show me my calendar for Friday", ("event_list", "plan_day"), {"filter": "week"}),
    _make_query("query-5", "do I have any overdue tasks", ("task_list",), {"filter": "overdue"}),
    _make_query("query-6", "what meetings do I have next week", ("event_list",), {"filter": "week"}),

    # ---- No tool needed (6) ----
    _case("none-1", "no tool needed", "thanks", None, {}, description="Small talk; no tool."),
    _case("none-2", "no tool needed", "hello", None, {}, description="Greeting; no tool."),
    _case("none-3", "no tool needed", "what does FTS5 stand for", None, {},
          description="General knowledge question; no tool."),
    _case("none-4", "no tool needed", "how do I set a reminder", None, {}, description="Help question; no tool."),
    _case("none-5", "no tool needed", "great, that worked", None, {}, description="Acknowledgment; no tool."),
    _case("none-6", "no tool needed", "can you help me", None, {}, description="Open help offer; no tool."),

    # ---- Confirm-class action (3): never done directly ----
    _case("confirm-1", "confirm-class action", "send the draft to Ravi", "email_draft", {"to": "Ravi"},
          _prepare_or_ask("email_draft", "email_send", "email_search"),
          description="Sending is class C: draft or look up, never claim it was sent."),
    _case("confirm-2", "confirm-class action", "delete all my completed tasks", "task_list", {"filter": "done"},
          _not_tool("task_delete"), description="Bulk delete is not offered: list or ask, never delete."),
    _case("confirm-3", "confirm-class action", "invite Sarah to the meeting", None, {},
          _not_tool("event_create", "event_update", "email_send"),
          description="Attendees are class C and unsupported: ask or explain, do not change events."),

    # ---- Ambiguous, must ask (3) ----
    _case("ambig-1", "ambiguous must ask", "remind me about the thing", None, {}, _asks_no_tool, must_ask=True,
          description="Ambiguous item; agent must ask one question, call no tool."),
    _case("ambig-2", "ambiguous must ask", "delete that task", None, {}, _lookup_or_ask("task_list"), must_ask=True,
          description="Ambiguous reference; ask which task. A read-only task_list lookup is allowed, "
                      "deleting or changing anything is not."),
    _case("ambig-3", "ambiguous must ask", "remind me at 5", None, {}, _asks_no_tool, must_ask=True,
          description="A bare hour is ambiguous (5 AM or 5 PM); agent must ask, not create."),

    # ---- Recurring event (2): one call with recurrence_text, never a one-off ----
    _case("event-recur-1", "recurring event",
          "set a task on my calendar to focus on my course every day, 4pm to 6pm", "event_create",
          {"title": "Focus on course", "when_text": "4pm", "duration_text": "2 hours",
           "recurrence_text": "every day"},
          _tool("event_create", recurrence_text=("day",)),
          description="Repeating calendar block: event_create with recurrence_text."),
    _case("event-recur-2", "recurring event", "put a 15 minute standup on my calendar every weekday at 10am",
          "event_create",
          {"title": "Standup", "when_text": "10am", "duration_text": "15 minutes", "recurrence_text": "every weekday"},
          _tool("event_create", recurrence_text=("weekday",)),
          description="Repeating calendar block on weekdays."),
]

_COUNTS = Counter(c.category for c in CASES)
assert len(CASES) == 42, f"expected 42 cases, got {len(CASES)}"
assert _COUNTS["create task"] == 6
assert _COUNTS["reminder relative"] == 6
assert _COUNTS["reminder absolute/day-first"] == 6
assert _COUNTS["recurring reminder"] == 4
assert _COUNTS["query"] == 6
assert _COUNTS["no tool needed"] == 6
assert _COUNTS["confirm-class action"] == 3
assert _COUNTS["ambiguous must ask"] == 3
assert _COUNTS["recurring event"] == 2
