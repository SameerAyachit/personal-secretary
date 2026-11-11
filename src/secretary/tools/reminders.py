"""Reminder tools (plan §8.5, §9, §10).

``reminder_create`` is class B: it resolves the user's ``when_text`` in code
(via timeparse), writes a scheduled reminder row, and echoes the resolved fire
time. ``reminder_list`` is class A. ``reminder_snooze`` and ``reminder_cancel``
are class B. Time is resolved by code -- no tool accepts an absolute timestamp
from the LLM.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from secretary.store.db import Connection
from secretary.store.repos import reminders as reminders_repo
from secretary.timeparse.recurrence import (
    UnparseableRecurrence,
    parse_recurrence,
)
from secretary.timeparse.when import resolve_when
from secretary.tools.idempotency import idempotency_key
from secretary.tools.registry import SafetyClass, ToolSpec

_DEFAULT_TZ = "Asia/Kolkata"
_DEDUPE_WINDOW_SECONDS = 60


def _utc_now() -> datetime:
    """Current UTC time. Overridable in tests to freeze the clock."""
    return datetime.now(UTC)


class ReminderCreateArgs(BaseModel):
    title: str = Field(..., description="Reminder title in the user's words")
    when_text: str = Field(..., description="Fire time in the user's words, e.g. 'in 1 minute'")
    recurrence_text: str | None = Field(
        None, description="Recurrence rule, e.g. 'every weekday at 8:30'"
    )
    priority: int = Field(0, description="Priority (0 normal, 1 high)")
    tz: str = Field(_DEFAULT_TZ, description="Time zone for the reminder")


class ReminderListArgs(BaseModel):
    filter: str = Field(
        "open", description="open|today|tomorrow|week|overdue|all"
    )
    query: str | None = Field(None, description="Optional text to match against titles")


class ReminderRefArgs(BaseModel):
    reminder_ref: str = Field(..., description="Reminder id or title fragment")


class ReminderSnoozeArgs(ReminderRefArgs):
    snooze_text: str = Field(..., description="Snooze duration, e.g. '10 minutes'")


def _fire_local_iso(fire_utc: datetime, tz: str) -> str:
    return fire_utc.astimezone(ZoneInfo(tz)).strftime("%a %d %b, %I:%M %p %Z")


def _dedupe_existing(
    conn: Connection, title: str, fire_utc: datetime
) -> dict | None:
    """Return an existing scheduled reminder with the same title firing within
    the dedupe window, else None (plan §8.3)."""
    window_start = (fire_utc - timedelta(seconds=_DEDUPE_WINDOW_SECONDS)).isoformat()
    window_end = (fire_utc + timedelta(seconds=_DEDUPE_WINDOW_SECONDS)).isoformat()
    rows = reminders_repo.list_all(conn, status="scheduled")
    for row in rows:
        if row["title"].lower() != title.lower():
            continue
        nfa = row.get("next_fire_at")
        if not nfa:
            continue
        try:
            nfa_dt = datetime.fromisoformat(nfa)
        except ValueError:
            continue
        if nfa_dt.tzinfo is None:
            nfa_dt = nfa_dt.replace(tzinfo=UTC)
        if window_start <= nfa_dt.isoformat() <= window_end:
            return row
    return None


def reminder_create(conn: Connection, turn_id: str, args: dict) -> dict:
    parsed = ReminderCreateArgs(**args)
    now = _utc_now()
    tz = parsed.tz
    try:
        fire_local = resolve_when(parsed.when_text, now, tz)
    except Exception as exc:
        return {"error": f"could not resolve time '{parsed.when_text}': {exc}"}
    fire_utc = fire_local.astimezone(UTC)

    existing = _dedupe_existing(conn, parsed.title, fire_utc)
    if existing is not None:
        return {
            "reminder_id": existing["id"],
            "title": existing["title"],
            "fire_at_local": _fire_local_iso(
                datetime.fromisoformat(existing["next_fire_at"]).replace(tzinfo=UTC), tz
            ),
            "note": "Duplicate reminder already scheduled at that time.",
            "idempotency_key": existing.get("idempotency_key"),
        }

    rule_json = None
    kind = "once"
    if parsed.recurrence_text:
        try:
            rule = parse_recurrence(parsed.recurrence_text, tz)
            rule_json = rule.to_json()
            kind = "recurring"
        except UnparseableRecurrence as exc:
            return {"error": f"could not parse recurrence '{parsed.recurrence_text}': {exc}"}

    key = idempotency_key(turn_id, "reminder_create", parsed.model_dump())
    # If a reminder with this idempotency key already exists (any status),
    # return its info instead of risking a UNIQUE constraint violation.
    existing = reminders_repo.get_by_idempotency_key(conn, key)
    if existing is not None:
        return {
            "reminder_id": existing["id"],
            "title": existing["title"],
            "fire_at_local": _fire_local_iso(
                datetime.fromisoformat(existing["next_fire_at"]).replace(tzinfo=UTC), tz
            ),
            "kind": existing["kind"],
            "idempotency_key": existing.get("idempotency_key"),
            "note": "A reminder with this title and time already exists.",
        }
    try:
        reminder_id = reminders_repo.create(
            conn,
            task_id=None,
            title=parsed.title,
            body="",
            kind=kind,
            tz=tz,
            rule_json=rule_json,
            next_fire_at=fire_utc.isoformat(),
            priority=parsed.priority,
            idempotency_key=key,
            turn_id=turn_id,
        )
    except sqlite3.IntegrityError:
        # Race: another process created it between our check and insert.
        existing = reminders_repo.get_by_idempotency_key(conn, key)
        if existing is not None:
            return {
                "reminder_id": existing["id"],
                "title": existing["title"],
                "fire_at_local": _fire_local_iso(
                    datetime.fromisoformat(existing["next_fire_at"]).replace(tzinfo=UTC), tz
                ),
                "kind": existing["kind"],
                "idempotency_key": existing.get("idempotency_key"),
                "note": "A reminder with this title and time already exists.",
            }
        raise
    return {
        "reminder_id": reminder_id,
        "title": parsed.title,
        "fire_at_local": _fire_local_iso(fire_local, tz),
        "kind": kind,
        "idempotency_key": key,
    }


def reminder_list(conn: Connection, turn_id: str, args: dict) -> dict:
    parsed = ReminderListArgs(**args)
    rows = reminders_repo.list_all(conn)
    reminders: list[dict] = []
    for row in rows:
        title = row["title"]
        if parsed.query and parsed.query.lower() not in title.lower():
            continue
        reminders.append(
            {
                "id": row["id"],
                "title": title,
                "next_fire_at": row.get("next_fire_at"),
                "status": row.get("status"),
                "kind": row.get("kind"),
            }
        )
    return {"reminders": reminders, "filter": parsed.filter}


def _resolve_reminder_ref(conn: Connection, ref: str) -> int | None:
    """Resolve reminder_ref: exact integer id, else title match."""
    try:
        return int(ref)
    except (TypeError, ValueError):
        pass
    rows = reminders_repo.list_all(conn, status="scheduled")
    for row in rows:
        if row["title"].lower() == ref.lower():
            return int(row["id"])
    for row in rows:
        if ref.lower() in row["title"].lower():
            return int(row["id"])
    return None


def reminder_cancel(conn: Connection, turn_id: str, args: dict) -> dict:
    parsed = ReminderRefArgs(**args)
    reminder_id = _resolve_reminder_ref(conn, parsed.reminder_ref)
    if reminder_id is None:
        return {"error": f"no reminder matches '{parsed.reminder_ref}'"}
    ok = reminders_repo.soft_delete(conn, reminder_id, turn_id=turn_id)
    if not ok:
        return {"error": f"reminder {reminder_id} could not be cancelled"}
    return {"reminder_id": reminder_id, "status": "cancelled"}


def _parse_snooze_minutes(snooze_text: str) -> int | None:
    text = (snooze_text or "").strip().lower()
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(min|mins|minute|minutes)\s*$", text)
    if m:
        return round(float(m.group(1)))
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours)\s*$", text)
    if m:
        return round(float(m.group(1)) * 60)
    return None


def reminder_snooze(conn: Connection, turn_id: str, args: dict) -> dict:
    parsed = ReminderSnoozeArgs(**args)
    reminder_id = _resolve_reminder_ref(conn, parsed.reminder_ref)
    if reminder_id is None:
        return {"error": f"no reminder matches '{parsed.reminder_ref}'"}
    minutes = _parse_snooze_minutes(parsed.snooze_text)
    if minutes is None:
        return {"error": f"could not parse snooze '{parsed.snooze_text}'"}
    now = _utc_now()
    next_fire = now + timedelta(minutes=minutes)
    ok = reminders_repo.update(
        conn,
        reminder_id,
        next_fire_at=next_fire.isoformat(),
        status="scheduled",
        turn_id=turn_id,
    )
    if not ok:
        return {"error": f"reminder {reminder_id} could not be snoozed"}
    return {
        "reminder_id": reminder_id,
        "snoozed_until_local": next_fire.astimezone(ZoneInfo(_DEFAULT_TZ)).strftime(
            "%a %d %b, %I:%M %p"
        ),
    }


def register(registry) -> None:
    registry.register(
        ToolSpec(
            name="reminder_create",
            group="core",
            safety_class=SafetyClass.B,
            description="Create a reminder",
            args_model=ReminderCreateArgs,
            fn=reminder_create,
        )
    )
    registry.register(
        ToolSpec(
            name="reminder_list",
            group="core",
            safety_class=SafetyClass.A,
            description="List reminders",
            args_model=ReminderListArgs,
            fn=reminder_list,
        )
    )
    registry.register(
        ToolSpec(
            name="reminder_snooze",
            group="core",
            safety_class=SafetyClass.B,
            description="Snooze a reminder",
            args_model=ReminderSnoozeArgs,
            fn=reminder_snooze,
        )
    )
    registry.register(
        ToolSpec(
            name="reminder_cancel",
            group="core",
            safety_class=SafetyClass.B,
            description="Cancel a reminder",
            args_model=ReminderRefArgs,
            fn=reminder_cancel,
        )
    )
