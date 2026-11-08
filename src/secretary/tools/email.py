"""Email send tool (Class C: never executes from the LLM turn, plan §8.2)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from secretary.store.db import Connection
from secretary.store.repos import pending_actions as pa_repo
from secretary.tools.registry import SafetyClass, ToolSpec


class EmailSendArgs(BaseModel):
    draft_ref: str = Field(..., description="Draft to send")


def email_send_prepare(conn: Connection, turn_id: str, args: dict) -> dict:
    """Prepare a Class C send for approval; does NOT send (plan §8.2)."""
    parsed = EmailSendArgs(**args)
    expires_at = (datetime.now(UTC) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {"draft_ref": parsed.draft_ref}
    summary = f"Send email draft {parsed.draft_ref}"
    pending_id = pa_repo.create(
        conn,
        kind="email.send",
        summary=summary,
        payload_json=json.dumps(payload),
        expires_at=expires_at,
        turn_id=turn_id,
    )
    return {
        "pending_id": pending_id,
        "summary": summary,
        "status": "waiting",
        "expires_at": expires_at,
        "note": "Class C: awaiting user approval in the Approvals view.",
    }


def register(registry) -> None:
    registry.register(
        ToolSpec(
            name="email_send",
            group="email",
            safety_class=SafetyClass.C,
            description="Send an email draft (requires approval)",
            args_model=EmailSendArgs,
            fn=email_send_prepare,
        )
    )
