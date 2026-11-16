"""Read questions must be offered a read tool (live eval query-6: "what meetings do I have next week"
reached the model with only event_create, so it created an event instead of listing)."""

from __future__ import annotations

import pytest

from secretary.agent.wiring import build_registry_and_router

_CTX = {"now": "2026-11-16T10:00", "tz": "Asia/Kolkata", "today_iso": "2026-11-16"}


@pytest.mark.parametrize(
    "text",
    [
        "what meetings do I have next week",
        "do I have any appointments on Friday",
        "am I busy tomorrow afternoon",
        "what's on my plate tomorrow",
        "show me my calendar for Friday",
        "what's my schedule today",
        "any events this weekend",
    ],
)
def test_event_list_is_offered_for_questions_about_the_calendar(text):
    _registry, router = build_registry_and_router()
    names = {spec.name for spec in router.select(text, _CTX)}
    assert "event_list" in names, text


def test_unrelated_text_does_not_pull_in_the_calendar_tools():
    _registry, router = build_registry_and_router()
    names = {spec.name for spec in router.select("add a task to buy groceries", _CTX)}
    assert "event_list" not in names
