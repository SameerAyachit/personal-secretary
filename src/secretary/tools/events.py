"""Calendar event tools (plan §8.5, §13).

``event_create`` is class B (own event, no attendees): it resolves the user's
``when_text`` in code and writes through ``events_repo``. ``event_list`` is
class A (read). Every time-bearing tool takes ``when_text`` -- never an
absolute timestamp from the LLM.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from secretary.store.db import Connection
from secretary.store.repos import events as events_repo
from secretary.timeparse.when import resolve_when
from secretary.tools.registry import SafetyClass, ToolSpec

_DEFAULT_TZ = "Asia/Kolkata"


def _duration_minutes(duration_text: str) -> int:
    text = (duration_text or "1 hour").strip().lower()
    match = re.match(
        r"\s*(\d+(?:\.\d+)?)\s*(min|mins|minute|minutes|h|hr|hrs|hour|hours)\s*$", text
    )
    if not match:
        return 60
    value = float(match.group(1))
    unit = match.group(2)
    if unit.startswith("h"):
        return round(value * 60)
    return round(value)


class EventCreateArgs(BaseModel):
    title: str = Field(..., description="Event title in the user's words")
    when_text: str = Field(..., description="Start time in the user's words")
    duration_text: str = Field("1 hour", description="Duration, e.g. '30 minutes' or '1 hour'")
    location: str | None = Field(None, description="Optional location")
    tz: str = Field(_DEFAULT_TZ, description="Time zone for the event")


def event_create(conn: Connection, turn_id: str, args: dict) -> dict:
    parsed = EventCreateArgs(**args)
    now = datetime.now(UTC)
    start = resolve_when(parsed.when_text, now, parsed.tz)
    end = start + timedelta(minutes=_duration_minutes(parsed.duration_text))
    event_id = events_repo.create(
        conn,
        title=parsed.title,
        start_at=start.astimezone(UTC).isoformat(),
        end_at=end.astimezone(UTC).isoformat(),
        tz=parsed.tz,
        all_day=0,
        location=parsed.location,
        turn_id=turn_id,
    )
    return {"event_id": event_id, "title": parsed.title, "start_at": start.isoformat()}


class EventListArgs(BaseModel):
    filter: str = Field("week", description="today|tomorrow|week")
    query: str | None = Field(None, description="Optional text to match against titles")


def _window_for(filter_name: str, now: datetime) -> tuple[str, str]:
    if filter_name == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif filter_name == "tomorrow":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        end = start + timedelta(days=1)
    else:  # week (default)
        start = now
        end = now + timedelta(days=7)
    return start.isoformat(), end.isoformat()


def event_list(conn: Connection, turn_id: str, args: dict) -> dict:
    parsed = EventListArgs(**args)
    now = datetime.now(UTC)
    start, end = _window_for(parsed.filter, now)
    rows = events_repo.list_window(conn, start_at=start, end_at=end)
    events = [
        {"id": r["id"], "title": r["title"], "start_at": r["start_at"]} for r in rows
    ]
    if parsed.query:
        q = parsed.query.lower()
        events = [e for e in events if q in e["title"].lower()]
    return {"events": events, "filter": parsed.filter}


def register(registry) -> None:
    registry.register(
        ToolSpec(
            name="event_create",
            group="calendar",
            safety_class=SafetyClass.B,
            description="Create a calendar event",
            args_model=EventCreateArgs,
            fn=event_create,
        )
    )
    registry.register(
        ToolSpec(
            name="event_list",
            group="calendar",
            safety_class=SafetyClass.A,
            description="List calendar events",
            args_model=EventListArgs,
            fn=event_list,
        )
    )
