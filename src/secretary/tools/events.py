"""Calendar event tools (plan §8.5, §13).

``event_create`` is class B (own event, no attendees): it resolves the user's
``when_text`` in code and writes through ``events_repo``. ``event_list`` is
class A (read). Every time-bearing tool takes ``when_text`` -- never an
absolute timestamp from the LLM.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from secretary.config import default_timezone
from secretary.integrations.google.oauth import connected as google_connected
from secretary.store.db import Connection
from secretary.store.repos import events as events_repo
from secretary.timeparse.when import resolve_date, resolve_when
from secretary.tools.registry import SafetyClass, ToolSpec


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
    when_text: str = Field(..., description="Start time (or date for all-day events) in the user's words")
    duration_text: str = Field("1 hour", description="Duration, e.g. '30 minutes' or '1 hour'")
    location: str | None = Field(None, description="Optional location")
    tz: str = Field(default_factory=default_timezone, description="Time zone for the event")
    all_day: bool = Field(False, description="All-day event: when_text is a date and the event occupies the whole day")


def _day_bounds(day_text: str, now: datetime, tz: str) -> tuple[datetime, datetime]:
    """Resolve an all-day date to [local midnight, next local midnight)."""
    zone = ZoneInfo(tz)
    day = resolve_date(day_text, now, tz)
    start_local = datetime(day.year, day.month, day.day, tzinfo=zone)
    return start_local, start_local + timedelta(days=1)


def event_create(conn: Connection, turn_id: str, args: dict) -> dict:
    parsed = EventCreateArgs(**args)
    now = datetime.now(UTC)
    if parsed.all_day:
        start_local, end_local = _day_bounds(parsed.when_text, now, parsed.tz)
        all_day = 1
    else:
        start_local = resolve_when(parsed.when_text, now, parsed.tz)
        end_local = start_local + timedelta(minutes=_duration_minutes(parsed.duration_text))
        all_day = 0
    start_utc = start_local.astimezone(UTC)
    end_utc = end_local.astimezone(UTC)
    # Class B conflict warning: warn about overlapping EXISTING events before
    # inserting (so the new event is not flagged against itself).
    conflicts = _overlapping_events(conn, start_utc, end_utc)
    event_id = events_repo.create(
        conn,
        title=parsed.title,
        start_at=start_utc.isoformat(),
        end_at=end_utc.isoformat(),
        tz=parsed.tz,
        all_day=all_day,
        location=parsed.location,
        # Client-chosen Google id + pending state: the scheduler pushes the event
        # to Google Calendar, and a retry can never create a duplicate.
        google_event_id=uuid.uuid4().hex,
        sync_state="pending",
        turn_id=turn_id,
    )
    result = {"event_id": event_id, "title": parsed.title, "start_at": start_local.isoformat(), "all_day": bool(all_day)}
    # Be honest with the model: saved locally now, Google push happens in the
    # background and only if Google is connected.
    result["google"] = "queued" if google_connected() else "not_connected"
    if conflicts:
        result["conflicts"] = conflicts
    return result


def _overlapping_events(conn: Connection, start_utc: datetime, end_utc: datetime) -> list[dict]:
    """Return existing events that overlap [start_utc, end_utc) (class B conflict warning)."""
    q_start = (start_utc - timedelta(days=1)).isoformat()
    q_end = (end_utc + timedelta(days=1)).isoformat()
    rows = events_repo.list_window(conn, start_at=q_start, end_at=q_end)
    conflicts: list[dict] = []
    for row in rows:
        es = datetime.fromisoformat(row["start_at"])
        if es.tzinfo is None:
            es = es.replace(tzinfo=UTC)
        ee_raw = row["end_at"]
        ee = datetime.fromisoformat(ee_raw) if ee_raw else es + timedelta(hours=1)
        if ee.tzinfo is None:
            ee = ee.replace(tzinfo=UTC)
        if es < end_utc and start_utc < ee:
            conflicts.append({"title": row["title"], "start_at": row["start_at"], "end_at": row["end_at"]})
    return conflicts


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
        {"id": r["id"], "title": r["title"], "start_at": r["start_at"], "all_day": bool(r["all_day"])} for r in rows
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
