"""Note tools (plan §8.5): note_add (class B) and note_search (class A)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from secretary.store.db import Connection
from secretary.store.repos import notes as notes_repo
from secretary.tools.registry import SafetyClass, ToolSpec

_MAX_NOTE_CHARS = 4000


class NoteAddArgs(BaseModel):
    text: str = Field(..., description="The note, in the user's words")


class NoteSearchArgs(BaseModel):
    query: str = Field("", description="Words to find in notes; empty lists the latest notes")


def note_add(conn: Connection, turn_id: str, args: dict) -> dict:
    parsed = NoteAddArgs(**args)
    text = parsed.text.strip()
    if not text:
        return {"error": "the note is empty; ask the user what to write"}
    text = text[:_MAX_NOTE_CHARS]
    for row in notes_repo.list_recent(conn, limit=5):
        if row["text"].strip().lower() == text.lower():
            return {"note_id": row["id"], "note": "Same note already saved a moment ago."}
    note_id = notes_repo.create(conn, text=text, turn_id=turn_id)
    return {"note_id": note_id, "saved": True}


def note_search(conn: Connection, turn_id: str, args: dict) -> dict:
    parsed = NoteSearchArgs(**args)
    query = parsed.query.strip()
    rows = notes_repo.search(conn, query) if query else notes_repo.list_recent(conn, limit=20)
    return {
        "notes": [
            {"id": r["id"], "text": r["text"], "created_at": r["created_at"]} for r in rows
        ]
    }


def register(registry) -> None:
    registry.register(
        ToolSpec(
            name="note_add",
            group="core",
            safety_class=SafetyClass.B,
            description="Save a free-form note",
            args_model=NoteAddArgs,
            fn=note_add,
        )
    )
    registry.register(
        ToolSpec(
            name="note_search",
            group="core",
            safety_class=SafetyClass.A,
            description="Find saved notes by words, or list the latest",
            args_model=NoteSearchArgs,
            fn=note_search,
        )
    )
