"""Email tools (plan §3.5, §8.5).

email_search / email_read / email_triage are class A (quarantined reads: their
results are untrusted text and must be wrapped as <untrusted> data by the agent
loop). email_draft is class B (draft only). email_send is class C (approval
first). Triage classification is an injected callback (LLM-backed in
production; credentials human-gated).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from secretary.store.db import Connection
from secretary.store.repos import messages as messages_repo
from secretary.store.repos import pending_actions as pa_repo
from secretary.tools.registry import SafetyClass, ToolSpec

logger = logging.getLogger(__name__)

_TRIAGE_BODY_CHARS = 500  # body cap per triage run (plan §3.5: ~500 tokens)
_TRIAGE_LIMIT = 15        # cap messages per triage run

_classify: object = None  # set via configure_triage; LLM-backed, no-tools, in production


def configure_triage(classify) -> None:
    """Register the message classifier: message dict -> {category, urgency, suggested_action} enums."""
    globals()["_classify"] = classify


class EmailSearchArgs(BaseModel):
    query: str = Field(..., description="Words to match against email subjects and bodies")


class EmailReadArgs(BaseModel):
    message_ref: str = Field(..., description="Message id (integer)")


class EmailTriageArgs(BaseModel):
    scope: Literal["inbox"] = Field("inbox", description="Scope to triage (only 'inbox' supported)")


class EmailDraftArgs(BaseModel):
    to: str = Field(..., description="Recipient address")
    subject: str = Field(..., description="Subject line")
    body: str = Field(..., description="Body text")
    reply_to_ref: str | None = Field(None, description="Message id this replies to")


def email_search(conn: Connection, turn_id: str, args: dict) -> dict:
    """Search local messages by subject/body/from (class A, quarantined read)."""
    parsed = EmailSearchArgs(**args)
    rows = messages_repo.list_search(conn, parsed.query)
    return {
        "query": parsed.query,
        "messages": [
            {
                "id": r["id"],
                "from": r["from_addr"],
                "subject": r["subject"],
                "received_at": r["received_at"],
                "is_read": bool(r["is_read"]),
            }
            for r in rows
        ],
    }


def email_read(conn: Connection, turn_id: str, args: dict) -> dict:
    """Read one message and mark it read (class A, quarantined read)."""
    parsed = EmailReadArgs(**args)
    try:
        message_id = int(parsed.message_ref)
    except ValueError:
        return {"error": "message_ref must be a message id (integer)"}
    message = messages_repo.get(conn, message_id)
    if message is None:
        return {"error": "message not found"}
    messages_repo.mark_read(conn, message_id)
    return {
        "message": {
            "id": message["id"],
            "from": message["from_addr"],
            "to": message["to_addrs"],
            "subject": message["subject"],
            "body": message["body"],
            "received_at": message["received_at"],
            "is_read": True,
            "source": message["source"],
        }
    }


def email_draft(conn: Connection, turn_id: str, args: dict) -> dict:
    """Record a draft (class B: draft only, no send)."""
    parsed = EmailDraftArgs(**args)
    message_id = messages_repo.create(
        conn,
        from_addr="me",
        to_addrs=json.dumps([parsed.to]),
        subject=parsed.subject,
        body=parsed.body,
        received_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        source="draft",
        turn_id=turn_id,
    )
    return {
        "draft_id": message_id,
        "to": parsed.to,
        "subject": parsed.subject,
        "status": "draft",
        "note": "Draft saved; not sent.",
    }


def _counts(items: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item[key]] = counts.get(item[key], 0) + 1
    return counts


def triage_run(conn: Connection, turn_id: str, args: dict) -> dict:
    """Triaging unread inbox messages: enum classification, results stored locally (class A)."""
    parsed = EmailTriageArgs(**args)
    if _classify is None:
        return {"error": "triage classify callback not configured", "scope": parsed.scope}
    messages = messages_repo.list_unread(conn, limit=_TRIAGE_LIMIT)
    items: list[dict] = []
    for message in messages:
        body = (message.get("body") or "")[:_TRIAGE_BODY_CHARS]
        payload = {
            "id": message["id"],
            "thread_id": message.get("thread_id", ""),
            "from": message["from_addr"],
            "subject": message.get("subject") or "",
            "body": body,
        }
        try:
            outcome = _classify(payload)
        except Exception as exc:
            logger.warning("triage classify failed for message %s: %s", message["id"], exc)
            continue
        try:
            messages_repo.upsert_triage_result(
                conn,
                message["id"],
                outcome["category"],
                outcome["urgency"],
                outcome["suggested_action"],
                turn_id,
            )
        except (KeyError, ValueError) as exc:
            logger.warning("triage result invalid for message %s: %s", message["id"], exc)
            continue
        items.append({
            "message_id": message["id"],
            "from": message["from_addr"],
            "subject": message.get("subject") or "",
            "category": outcome["category"],
            "urgency": outcome["urgency"],
            "suggested_action": outcome["suggested_action"],
        })
    return {
        "scope": parsed.scope,
        "triaged": len(items),
        "by_category": _counts(items, "category"),
        "by_urgency": _counts(items, "urgency"),
        "items": items,
    }


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
            name="email_search",
            group="email",
            safety_class=SafetyClass.A,
            description="Search email by subject, body or sender",
            args_model=EmailSearchArgs,
            fn=email_search,
        )
    )
    registry.register(
        ToolSpec(
            name="email_read",
            group="email",
            safety_class=SafetyClass.A,
            description="Read one email message by id",
            args_model=EmailReadArgs,
            fn=email_read,
        )
    )
    registry.register(
        ToolSpec(
            name="email_triage",
            group="email",
            safety_class=SafetyClass.A,
            description="Triaging unread inbox messages into category/urgency/action enums",
            args_model=EmailTriageArgs,
            fn=triage_run,
        )
    )
    registry.register(
        ToolSpec(
            name="email_draft",
            group="email",
            safety_class=SafetyClass.B,
            description="Save an email draft (does not send)",
            args_model=EmailDraftArgs,
            fn=email_draft,
        )
    )
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
