"""Core task tools (plan §8.5 catalogue)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from secretary.store.db import Connection
from secretary.store.repos import tasks as tasks_repo
from secretary.tools.idempotency import idempotency_key
from secretary.tools.registry import SafetyClass, ToolSpec


class TaskCreateArgs(BaseModel):
    title: str = Field(..., description="Task title in the user's words")
    notes: str = ""
    when_text: str | None = Field(None, description="Due time in the user's words")
    priority: int = 0


def task_create(conn: Connection, turn_id: str, args: dict) -> dict:
    parsed = TaskCreateArgs(**args)
    key = idempotency_key(turn_id, "task_create", parsed.model_dump())
    task_id = tasks_repo.create(
        conn,
        title=parsed.title,
        notes=parsed.notes,
        source="agent",
        turn_id=turn_id,
    )
    return {"task_id": task_id, "title": parsed.title, "idempotency_key": key}


class TaskListArgs(BaseModel):
    filter: str = Field("open", description="open|today|tomorrow|week|overdue|done")
    query: str | None = None


def task_list(conn: Connection, turn_id: str, args: dict) -> dict:
    TaskListArgs(**args)  # validate args
    rows = tasks_repo.list_open(conn)
    return {"tasks": [{"id": r["id"], "title": r["title"]} for r in rows]}


def register(registry) -> None:
    registry.register(
        ToolSpec(
            name="task_create",
            group="core",
            safety_class=SafetyClass.B,
            description="Create a task",
            args_model=TaskCreateArgs,
            fn=task_create,
        )
    )
    registry.register(
        ToolSpec(
            name="task_list",
            group="core",
            safety_class=SafetyClass.A,
            description="List tasks",
            args_model=TaskListArgs,
            fn=task_list,
        )
    )
