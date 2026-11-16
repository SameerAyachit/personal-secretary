"""Tool registry + keyword router wiring (plan A7), shared by the app and selftest."""

from __future__ import annotations

from secretary.agent.router import Router
from secretary.tools import email as email_tools
from secretary.tools import events as events_tools
from secretary.tools import memory as memory_tools
from secretary.tools import notes as notes_tools
from secretary.tools import planning as planning_tools
from secretary.tools import registry as tools_registry
from secretary.tools import reminders as reminders_tools
from secretary.tools import research as research_tools
from secretary.tools import search as search_tools
from secretary.tools import tasks as tasks_tools


def build_registry_and_router() -> tuple[tools_registry.Registry, Router]:
    """Register every tool and map non-core tools to keyword triggers.

    Task, reminder and memory tools are in the always-on ``core`` group, so
    they need no keyword routes.
    """
    registry = tools_registry.Registry()
    for module in (
        tasks_tools,
        email_tools,
        events_tools,
        planning_tools,
        reminders_tools,
        memory_tools,
        notes_tools,
        research_tools,
        search_tools,
    ):
        module.register(registry)
    router = Router(registry)
    router.route("email_search", ["email", "mail", "inbox", "message", "unread"])
    router.route("email_read", ["email", "mail", "message", "read"])
    router.route("email_triage", ["triage", "email", "mail", "inbox"])
    router.route("email_draft", ["draft", "email", "mail", "reply"])
    router.route("email_send", ["send", "email"])
    router.route("web_search", ["search", "web"])
    router.route("event_create", ["event", "calendar", "meeting", "appointment"])
    router.route("event_update", ["event", "calendar", "meeting", "appointment", "reschedule", "move", "change"])
    # Read questions ("what meetings do I have", "am I busy") must always be offered the read
    # tool; with only event_create in hand the model created an event instead (live eval query-6).
    router.route(
        "event_list",
        ["event", "calendar", "schedule", "agenda", "meeting", "appointment", "busy",
         "what's on", "whats on", "plate", "do i have"],
    )
    router.route("plan_day", ["plan", "planning", "schedule", "free", "slot"])
    router.route("research_brief", ["research", "brief", "summarize"])
    router.route("check_claims", ["check", "claims", "verify", "source"])
    return registry, router
