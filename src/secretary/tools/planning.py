"""Planning tools (plan §13 / §8.5 catalogue).

``plan_day`` is class A (read): it finds free slots in the calendar for a day
and returns them as structured data for the LLM to phrase. No absolute
timestamps are accepted from the LLM -- dates come through ``date_text``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from secretary.config import default_timezone
from secretary.store.db import Connection
from secretary.store.repos import events as events_repo
from secretary.timeparse.when import resolve_date
from secretary.tools.registry import SafetyClass, ToolSpec

_WORK_START_HOUR = 9
_WORK_END_HOUR = 17


class PlanDayArgs(BaseModel):
    date_text: str | None = Field(None, description="Date, e.g. 'tomorrow' or '2026-11-09'")
    tz: str = Field(default_factory=default_timezone, description="Time zone for the day")
    min_duration_minutes: int = Field(30, ge=1, description="Minimum free-slot length in minutes")


def _to_local(iso_value: str | None, zone) -> datetime:
    if iso_value is None:
        return None
    return datetime.fromisoformat(iso_value).astimezone(zone)


def plan_day(conn: Connection, turn_id: str, args: dict) -> dict:
    parsed = PlanDayArgs(**args)
    zone = ZoneInfo(parsed.tz)
    now_local = datetime.now(UTC).astimezone(zone)
    target = resolve_date(parsed.date_text, now_local, parsed.tz) if parsed.date_text else now_local.date()

    day_start_local = datetime(target.year, target.month, target.day, tzinfo=zone)
    day_end_local = day_start_local + timedelta(days=1)
    rows = events_repo.list_window(
        conn,
        start_at=day_start_local.astimezone(UTC).isoformat(),
        end_at=day_end_local.astimezone(UTC).isoformat(),
    )

    work_start = day_start_local.replace(hour=_WORK_START_HOUR, minute=0, second=0, microsecond=0)
    work_end = day_start_local.replace(hour=_WORK_END_HOUR, minute=0, second=0, microsecond=0)

    busy: list[tuple[datetime, datetime]] = []
    for row in rows:
        start = _to_local(row["start_at"], zone)
        end = _to_local(row["end_at"], zone) or (start + timedelta(hours=1)) if start else None
        if start is None or end is None:
            continue
        busy.append((max(start, work_start), min(end, work_end)))
    busy = [(s, e) for s, e in busy if s < e]
    busy.sort()

    merged: list[tuple[datetime, datetime]] = []
    for start, end in busy:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    free_slots: list[dict] = []
    cursor = work_start
    for start, end in merged:
        if start > cursor:
            gap_minutes = (start - cursor).total_seconds() / 60
            if gap_minutes >= parsed.min_duration_minutes:
                free_slots.append({"start": cursor.isoformat(), "end": start.isoformat()})
        cursor = max(cursor, end)
    if cursor < work_end:
        gap_minutes = (work_end - cursor).total_seconds() / 60
        if gap_minutes >= parsed.min_duration_minutes:
            free_slots.append({"start": cursor.isoformat(), "end": work_end.isoformat()})

    return {
        "date": target.isoformat(),
        "tz": parsed.tz,
        "free_slots": free_slots,
    }


def register(registry) -> None:
    registry.register(
        ToolSpec(
            name="plan_day",
            group="planning",
            safety_class=SafetyClass.A,
            description="Find free slots in the day for planning",
            args_model=PlanDayArgs,
            fn=plan_day,
        )
    )
