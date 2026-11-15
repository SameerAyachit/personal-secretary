"""Core task tools (plan §8.5 catalogue).

Time is resolved in code from the user's own words (``when_text``); no tool
accepts an absolute timestamp from the LLM. A task reference is an id or a
text fragment; when a fragment matches several tasks the tool returns the
candidates and changes nothing, so the agent asks the user which one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from secretary.config import default_timezone
from secretary.store.db import Connection
from secretary.store.repos import tasks as tasks_repo
from secretary.store.repos import undo as undo_repo
from secretary.store.repos._base import now_utc
from secretary.timeparse.when import AmbiguousTime, PastTime, resolve_when
from secretary.tools.idempotency import idempotency_key
from secretary.tools.registry import SafetyClass, ToolSpec
from secretary.tools.timeerrors import time_error

_DEDUPE_WINDOW_SECONDS = 60


def _utc_now() -> datetime:
    """Current UTC time. Overridable in tests to freeze the clock."""
    return datetime.now(UTC)


def _local_text(due_at: str | None, tz: str) -> str | None:
    if not due_at:
        return None
    try:
        when = datetime.fromisoformat(due_at)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(ZoneInfo(tz)).strftime("%a %d %b, %I:%M %p")


def _resolve_due(when_text: str, tz: str) -> str:
    """Resolve ``when_text`` to a UTC ISO string; raises on anything unparseable."""
    return resolve_when(when_text, _utc_now(), tz).astimezone(UTC).isoformat()


def _brief(row: dict, tz: str) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "due_local": _local_text(row.get("due_at"), tz),
    }


# --------------------------------------------------------------------- create


class TaskCreateArgs(BaseModel):
    title: str = Field(..., description="Task title in the user's words")
    notes: str = ""
    when_text: str | None = Field(None, description="Due time in the user's words")
    priority: int = 0
    tz: str = Field(default_factory=default_timezone, description="Time zone for the due time")


def _recent_duplicate(conn: Connection, title: str) -> dict | None:
    """An open task with the same title created in the last minute (plan §8.3)."""
    cutoff = datetime.now(UTC) - timedelta(seconds=_DEDUPE_WINDOW_SECONDS)
    for row in tasks_repo.list_open(conn):
        if row["title"].strip().lower() != title.strip().lower():
            continue
        try:
            created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if created >= cutoff:
            return row
    return None


def task_create(conn: Connection, turn_id: str, args: dict) -> dict:
    parsed = TaskCreateArgs(**args)
    key = idempotency_key(turn_id, "task_create", parsed.model_dump(exclude={"tz"}))
    due_at = None
    if parsed.when_text:
        try:
            due_at = _resolve_due(parsed.when_text, parsed.tz)
        except (PastTime, AmbiguousTime) as exc:
            return time_error(exc, parsed.when_text)
    existing = _recent_duplicate(conn, parsed.title)
    if existing is not None:
        return {
            "task_id": existing["id"],
            "title": existing["title"],
            "idempotency_key": key,
            "note": "Duplicate task already created a moment ago.",
        }
    task_id = tasks_repo.create(
        conn,
        title=parsed.title,
        notes=parsed.notes,
        due_at=due_at,
        due_tz=parsed.tz if due_at else None,
        source="agent",
        turn_id=turn_id,
    )
    if parsed.priority:
        tasks_repo.update(conn, task_id, priority=parsed.priority, turn_id=turn_id)
    undo_repo.record(conn, turn_id, f"Added task '{parsed.title}'",
                     {"op": "soft_delete", "table": "tasks", "id": task_id})
    result = {"task_id": task_id, "title": parsed.title, "idempotency_key": key}
    if due_at:
        result["due_local"] = _local_text(due_at, parsed.tz)
    return result


# ----------------------------------------------------------------------- list


class TaskListArgs(BaseModel):
    filter: str = Field("open", description="open|today|tomorrow|week|overdue|done|search")
    query: str | None = Field(None, description="Words to match in the title or notes")
    tz: str = Field(default_factory=default_timezone, description="Time zone for the day filters")


def _due_local_date(row: dict, zone: ZoneInfo):
    if not row.get("due_at"):
        return None
    try:
        when = datetime.fromisoformat(row["due_at"])
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(zone).date()


def task_list(conn: Connection, turn_id: str, args: dict) -> dict:
    parsed = TaskListArgs(**args)
    zone = ZoneInfo(parsed.tz)
    now = _utc_now()
    today = now.astimezone(zone).date()
    wanted = parsed.filter.lower()
    rows = tasks_repo.list_all(conn, status="done" if wanted == "done" else "open")

    def keep(row: dict) -> bool:
        due = _due_local_date(row, zone)
        if wanted == "today":
            return due == today
        if wanted == "tomorrow":
            return due == today + timedelta(days=1)
        if wanted == "week":
            return due is not None and today <= due <= today + timedelta(days=6)
        if wanted == "overdue":
            return bool(row.get("due_at")) and datetime.fromisoformat(row["due_at"]).astimezone(UTC) < now
        return True

    rows = [r for r in rows if keep(r)]
    if parsed.query:
        needle = parsed.query.lower()
        rows = [r for r in rows if needle in f"{r['title']} {r.get('notes') or ''}".lower()]
    return {"tasks": [_brief(r, parsed.tz) for r in rows]}


# ------------------------------------------------------- reference resolution


def _resolve_ref(conn: Connection, ref: str, *, open_only: bool) -> tuple[dict | None, dict | None]:
    """Return (task, None) or (None, error-or-candidates result)."""
    ref = (ref or "").strip()
    if ref.isdigit():
        row = tasks_repo.get(conn, int(ref))
        if row is None or (open_only and row["status"] != "open"):
            return None, {"error": f"no task with id {ref}"}
        return row, None
    pool = tasks_repo.list_all(conn, status="open" if open_only else None)
    needle = ref.lower()
    exact = [r for r in pool if r["title"].strip().lower() == needle]
    matches = exact or [r for r in pool if needle and needle in r["title"].lower()]
    if not matches:
        return None, {"error": f"no task matches '{ref}'"}
    if len(matches) > 1:
        return None, {
            "candidates": [{"id": r["id"], "title": r["title"]} for r in matches[:5]],
            "note": "More than one task matches. Ask the user which one; nothing was changed.",
        }
    return matches[0], None


class TaskRefArgs(BaseModel):
    task_ref: str = Field(..., description="Task id or part of its title")


# --------------------------------------------------------------------- update


class TaskUpdateArgs(TaskRefArgs):
    title: str | None = Field(None, description="New title")
    notes: str | None = Field(None, description="New notes")
    when_text: str | None = Field(None, description="New due time in the user's words")
    priority: int | None = Field(None, description="New priority (0 normal, 1 high)")
    tz: str = Field(default_factory=default_timezone, description="Time zone for the due time")


def task_update(conn: Connection, turn_id: str, args: dict) -> dict:
    parsed = TaskUpdateArgs(**args)
    task, problem = _resolve_ref(conn, parsed.task_ref, open_only=False)
    if task is None:
        return problem or {"error": "task not found"}
    fields: dict = {}
    if parsed.title is not None:
        fields["title"] = parsed.title
    if parsed.notes is not None:
        fields["notes"] = parsed.notes
    if parsed.priority is not None:
        fields["priority"] = parsed.priority
    if parsed.when_text:
        try:
            fields["due_at"] = _resolve_due(parsed.when_text, parsed.tz)
        except (PastTime, AmbiguousTime) as exc:
            return time_error(exc, parsed.when_text)
        fields["due_tz"] = parsed.tz
    if not fields:
        return {"error": "nothing to change: give a new title, notes, time or priority"}
    prior = {key: task.get(key) for key in fields}
    tasks_repo.update(conn, task["id"], turn_id=turn_id, **fields)
    undo_repo.record(conn, turn_id, f"Edited task '{task['title']}'",
                     {"op": "set", "table": "tasks", "id": task["id"], "fields": prior})
    return {"task_id": task["id"], **_brief(tasks_repo.get(conn, task["id"]) or task, parsed.tz)}


# ------------------------------------------------------------ complete/delete


def task_complete(conn: Connection, turn_id: str, args: dict) -> dict:
    parsed = TaskRefArgs(**args)
    task, problem = _resolve_ref(conn, parsed.task_ref, open_only=True)
    if task is None:
        return problem or {"error": "task not found"}
    tasks_repo.update(conn, task["id"], status="done", completed_at=now_utc(), turn_id=turn_id)
    undo_repo.record(conn, turn_id, f"Completed task '{task['title']}'",
                     {"op": "set", "table": "tasks", "id": task["id"],
                      "fields": {"status": "open", "completed_at": None}})
    return {"task_id": task["id"], "title": task["title"], "status": "done"}


def task_delete(conn: Connection, turn_id: str, args: dict) -> dict:
    parsed = TaskRefArgs(**args)
    task, problem = _resolve_ref(conn, parsed.task_ref, open_only=False)
    if task is None:
        return problem or {"error": "task not found"}
    tasks_repo.soft_delete(conn, task["id"], turn_id=turn_id)
    undo_repo.record(conn, turn_id, f"Deleted task '{task['title']}'",
                     {"op": "restore", "table": "tasks", "id": task["id"]})
    return {"task_id": task["id"], "title": task["title"], "deleted": True}


def register(registry) -> None:
    specs = (
        ("task_create", SafetyClass.B, "Create a task, optionally with a due time in the user's words",
         TaskCreateArgs, task_create),
        ("task_list", SafetyClass.A, "List tasks: open, today, tomorrow, week, overdue, done, or search",
         TaskListArgs, task_list),
        ("task_update", SafetyClass.B, "Change a task's title, notes, due time or priority",
         TaskUpdateArgs, task_update),
        ("task_complete", SafetyClass.B, "Mark a task as done", TaskRefArgs, task_complete),
        ("task_delete", SafetyClass.B, "Delete one task (can be restored)", TaskRefArgs, task_delete),
    )
    for name, safety_class, description, args_model, fn in specs:
        registry.register(
            ToolSpec(
                name=name,
                group="core",
                safety_class=safety_class,
                description=description,
                args_model=args_model,
                fn=fn,
            )
        )
