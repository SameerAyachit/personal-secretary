"""Gmail triage background job (plan §13.4).

Runs as a step of the scheduler tick: syncs recent Gmail messages into the
local store (when a Gmail client is configured) and classifies unread
messages into category/urgency/suggested_action enums (when a classifier
callback is configured). Both dependencies are injectable; real Gmail
credentials and the LLM-backed classifier are human-gated (configured via
``secretary.tools.email.configure_triage``), so the job is a no-op by
default.

Every failure is logged and never stops the other tick steps (plan §10.1).
No network or LLM call runs inside the SQLite writer transaction.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from secretary.integrations.google.gmail import GmailClient, extract_body, extract_headers
from secretary.store.db import Connection
from secretary.store.repos import messages as messages_repo
from secretary.tools.email import _TRIAGE_BODY_CHARS, _TRIAGE_LIMIT

logger = logging.getLogger(__name__)

# Classify callback: message dict -> {"category", "urgency", "suggested_action"}
# using the enums from migrations/006_triage_results.sql.
Classify = Callable[[dict], dict]


def sync_gmail_messages(
    conn: Connection, gmail_client: GmailClient, turn_id: str, limit: int = _TRIAGE_LIMIT
) -> int:
    """Copy recent Gmail messages into the local store.

    Returns the number of newly stored messages. Messages already stored
    (matched by google_message_id) are skipped; a failure on one message
    does not abort the sync.
    """
    listed = gmail_client.list_messages(max_results=limit) or {}
    refs = listed.get("messages") or []
    fetched: list[dict] = []
    for ref in refs:
        google_id = ref.get("id")
        if not google_id:
            continue
        try:
            fetched.append(gmail_client.get_message(google_id, format="full"))
        except Exception as exc:  # one message must not abort the sync
            logger.warning("triage job: gmail get %s failed: %s", google_id, exc)

    def _store(con: sqlite3.Connection) -> int:
        stored = 0
        for msg in fetched:
            google_id = msg.get("id") or ""
            if not google_id or messages_repo.get_by_google_id(con, google_id) is not None:
                continue  # already stored
            headers = extract_headers(msg)
            date_raw = headers.get("Date", "")
            try:
                received_at = (
                    parsedate_to_datetime(date_raw).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                )
            except Exception:
                received_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            to_addrs = headers.get("To", "")
            messages_repo.create(
                con,
                thread_id=msg.get("threadId") or "",
                from_addr=headers.get("From", ""),
                to_addrs=json.dumps([to_addrs]) if to_addrs else "[]",
                subject=headers.get("Subject", ""),
                body=extract_body(msg),
                received_at=received_at,
                is_read=0 if "UNREAD" in (msg.get("labelIds") or []) else 1,
                source="gmail",
                google_message_id=google_id,
                turn_id=turn_id,
            )
            stored += 1
        return stored

    return conn.write(_store)


def run_triage_job(
    conn: Connection,
    gmail_client: GmailClient | None = None,
    classify: Classify | None = None,
    turn_id: str = "triage-job",
    limit: int = _TRIAGE_LIMIT,
) -> dict:
    """Run one triage job cycle: sync Gmail, then classify unread messages.

    Returns {"synced": n, "triaged": n, "by_category": {...}, "by_urgency": {...}}.
    """
    synced = 0
    if gmail_client is not None:
        try:
            synced = sync_gmail_messages(conn, gmail_client, turn_id, limit=limit)
            logger.info("triage job: synced %d gmail message(s)", synced)
        except Exception:  # never stops the tick
            logger.exception("triage job: gmail sync failed")

    triaged = 0
    by_category: dict[str, int] = {}
    by_urgency: dict[str, int] = {}
    classified: list[tuple[int, str, str, str]] = []  # (message_id, category, urgency, action)

    if classify is not None:
        # Read outside the writer transaction; classification (an LLM call)
        # must never run while holding the DB lock.
        try:
            messages = conn.read(
                lambda con: messages_repo.list_unread(con, limit=limit)
            )
        except Exception:
            logger.exception("triage job: could not read unread messages")
            messages = []
        for message in messages:
            body = (message.get("body") or "")[:_TRIAGE_BODY_CHARS]
            payload = {
                "id": message["id"],
                "thread_id": message.get("thread_id", ""),
                "from": message.get("from_addr", ""),
                "subject": message.get("subject") or "",
                "body": body,
            }
            try:
                outcome = classify(payload)
                category = outcome["category"]
                urgency = outcome["urgency"]
                suggested_action = outcome["suggested_action"]
            except Exception as exc:
                logger.warning("triage job: classification failed for message %s: %s", message["id"], exc)
                continue
            classified.append((message["id"], category, urgency, suggested_action))

        def _store(con: sqlite3.Connection) -> int:
            stored = 0
            for message_id, category, urgency, suggested_action in classified:
                try:
                    messages_repo.upsert_triage_result(
                        con, message_id, category, urgency, suggested_action, turn_id
                    )
                except ValueError as exc:
                    logger.warning(
                        "triage job: invalid triage result for message %s: %s", message_id, exc
                    )
                    continue
                stored += 1
                by_category[category] = by_category.get(category, 0) + 1
                by_urgency[urgency] = by_urgency.get(urgency, 0) + 1
            return stored

        try:
            triaged = conn.write(_store)
            logger.info("triage job: triaged %d message(s)", triaged)
        except Exception:  # never stops the tick
            logger.exception("triage job: classification store failed")

    return {
        "synced": synced,
        "triaged": triaged,
        "by_category": by_category,
        "by_urgency": by_urgency,
    }
