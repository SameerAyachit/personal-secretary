"""Memory facts tools (plan §8.5).

Facts are user-approved long-term memory stored in the ``facts`` table.
``memory_remember`` is class B and shown to the user; ``memory_forget`` is
class B. Facts are never used as ground truth for tasks or reminders (the DB
is) and are never presented as search results (plan §8.6, C-17).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from secretary.store.db import Connection
from secretary.store.repos import facts as facts_repo
from secretary.tools.idempotency import idempotency_key
from secretary.tools.registry import SafetyClass, ToolSpec


class MemoryRememberArgs(BaseModel):
    key: str = Field(..., description="Fact key in the user's words")
    value: str = Field(..., description="Fact value in the user's words")


class MemoryForgetArgs(BaseModel):
    key: str = Field(..., description="Fact key to remove")


def memory_remember(conn: Connection, turn_id: str, args: dict) -> dict:
    parsed = MemoryRememberArgs(**args)
    key = idempotency_key(turn_id, "memory_remember", parsed.model_dump())
    facts_repo.upsert(conn, parsed.key, parsed.value)
    return {"key": parsed.key, "value": parsed.value, "idempotency_key": key}


def memory_forget(conn: Connection, turn_id: str, args: dict) -> dict:
    parsed = MemoryForgetArgs(**args)
    key = idempotency_key(turn_id, "memory_forget", parsed.model_dump())
    forgot = facts_repo.delete(conn, parsed.key)
    return {"key": parsed.key, "forgot": forgot, "idempotency_key": key}


def register(registry) -> None:
    registry.register(
        ToolSpec(
            name="memory_remember",
            group="core",
            safety_class=SafetyClass.B,
            description="Remember a fact",
            args_model=MemoryRememberArgs,
            fn=memory_remember,
        )
    )
    registry.register(
        ToolSpec(
            name="memory_forget",
            group="core",
            safety_class=SafetyClass.B,
            description="Forget a fact",
            args_model=MemoryForgetArgs,
            fn=memory_forget,
        )
    )
