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
from secretary.store.repos import undo as undo_repo
from secretary.timeparse.when import AmbiguousTime, PastTime, resolve_date, resolve_when
from secretary.tools.registry import SafetyClass, ToolSpec
from secretary.tools.timeerrors import time_error


def _utc_now() -> datetime:
    """Current UTC time. Overridable in tests to freeze the clock."""
    return datetime.now(UTC)


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
    now = _utc_now()
    try:
        if parsed.all_day:
            start_local, end_local = _day_bounds(parsed.when_text, now, parsed.tz)
            all_day = 1
        else:
            start_local = resolve_when(parsed.when_text, now, parsed.tz)
            end_local = start_local + timedelta(minutes=_duration_minutes(parsed.duration_text))
            all_day = 0
    except (PastTime, AmbiguousTime) as exc:
        return time_error(exc, parsed.when_text)
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
    undo_repo.record(conn, turn_id, f"Created event '{parsed.title}'",
                     {"op": "soft_delete", "table": "events", "id": event_id})
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


class EventUpdateArgs(BaseModel):
    event_ref: str = Field(..., description="Event id or part of its title")
    title: str | None = Field(None, description="New title")
    when_text: str | None = Field(None, description="New start time (or date for all-day events)")
    duration_text: str | None = Field(None, description="New duration, e.g. '30 minutes'")
    location: str | None = Field(None, description="New location")
    tz: str = Field(default_factory=default_timezone, description="Time zone for the event")


def _resolve_event(conn: Connection, ref: str) -> tuple[dict | None, dict | None]:
    """Return (event, None) or (None, error-or-candidates); fragments never guess."""
    ref = (ref or "").strip()
    if ref.isdigit():
        row = events_repo.get(conn, int(ref))
        return (row, None) if row else (None, {"error": f"no event with id {ref}"})
    since = (_utc_now() - timedelta(days=1)).isoformat()
    pool = events_repo.list_from(conn, since=since)
    needle = ref.lower()
    exact = [r for r in pool if r["title"].strip().lower() == needle]
    matches = exact or [r for r in pool if needle and needle in r["title"].lower()]
    if not matches:
        return None, {"error": f"no upcoming event matches '{ref}'"}
    if len(matches) > 1:
        return None, {
            "candidates": [{"id": r["id"], "title": r["title"], "start_at": r["start_at"]} for r in matches[:5]],
            "note": "More than one event matches. Ask the user which one; nothing was changed.",
        }
    return matches[0], None


def event_update(conn: Connection, turn_id: str, args: dict) -> dict:
    """Change one of the user's own events (class B). Attendees are not supported."""
    parsed = EventUpdateArgs(**args)
    event, problem = _resolve_event(conn, parsed.event_ref)
    if event is None:
        return problem or {"error": "event not found"}
    fields: dict = {}
    if parsed.title is not None:
        fields["title"] = parsed.title
    if parsed.location is not None:
        fields["location"] = parsed.location
    old_start = datetime.fromisoformat(event["start_at"])
    old_end = datetime.fromisoformat(event["end_at"]) if event.get("end_at") else old_start + timedelta(hours=1)
    if parsed.when_text or parsed.duration_text:
        now = _utc_now()
        try:
            if event["all_day"]:
                if not parsed.when_text:
                    return {"error": "all-day events have no duration; give a new date"}
                start_local, end_local = _day_bounds(parsed.when_text, now, parsed.tz)
            else:
                start_local = (
                    resolve_when(parsed.when_text, now, parsed.tz) if parsed.when_text
                    else old_start.astimezone(ZoneInfo(parsed.tz))
                )
                length = (
                    timedelta(minutes=_duration_minutes(parsed.duration_text))
                    if parsed.duration_text else old_end - old_start
                )
                end_local = start_local + length
        except (PastTime, AmbiguousTime) as exc:
            return time_error(exc, parsed.when_text or "")
        fields["start_at"] = start_local.astimezone(UTC).isoformat()
        fields["end_at"] = end_local.astimezone(UTC).isoformat()
        fields["tz"] = parsed.tz
    if not fields:
        return {"error": "nothing to change: give a new title, time, duration or location"}
    events_repo.update(conn, event["id"], turn_id=turn_id, **fields)
    # Queue the change for Google (patched when the event already exists there).
    events_repo.set_sync_state(conn, event["id"], "pending")
    updated = events_repo.get(conn, event["id"]) or event
    return {
        "event_id": event["id"],
        "title": updated["title"],
        "start_at": datetime.fromisoformat(updated["start_at"]).astimezone(ZoneInfo(updated["tz"])).isoformat(),
        "all_day": bool(updated["all_day"]),
        "google": "queued" if google_connected() else "not_connected",
    }


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
            name="event_update",
            group="calendar",
            safety_class=SafetyClass.B,
            description="Change one of your own events: title, time, duration or location",
            args_model=EventUpdateArgs,
            fn=event_update,
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
