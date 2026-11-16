"""The system prompt carries the rules the live eval showed the model needs (ambig-3, query-6)."""

from __future__ import annotations

from secretary.agent.loop import SYSTEM_PROMPT


def test_prompt_tells_the_model_to_use_list_tools_for_schedule_questions():
    assert "event_list" in SYSTEM_PROMPT and "never a create tool" in SYSTEM_PROMPT


def test_prompt_tells_the_model_to_ask_am_or_pm_for_a_bare_hour():
    assert "AM or PM?" in SYSTEM_PROMPT and "remind me at 5" in SYSTEM_PROMPT
