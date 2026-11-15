"""Gmail read client (plan §13.4).

Read-only access to Gmail messages. Results are untrusted data from the web;
the agent loop wraps them as ``<untrusted>`` (Section 8.6).
"""

from __future__ import annotations

import base64
import logging
from email.message import EmailMessage

import httpx

from secretary.integrations.google.auth import GoogleAuth

logger = logging.getLogger(__name__)

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/{user_id}/messages"
GMAIL_MESSAGE_API = (
    "https://gmail.googleapis.com/gmail/v1/users/{user_id}/messages/{message_id}"
)
GMAIL_SEND_API = "https://gmail.googleapis.com/gmail/v1/users/{user_id}/messages/send"


class GmailError(Exception):
    """Raised when a Gmail API call fails."""


class GmailPermissionError(GmailError):
    """Raised on HTTP 401/403: the Google grant lacks permission (reconnect needed)."""


class GmailClient:
    """Thin client over Gmail v1 messages."""

    def __init__(self, auth: GoogleAuth, client: httpx.Client | None = None) -> None:
        self._auth = auth
        self._client = client or httpx.Client()

    def list_messages(
        self,
        user_id: str = "me",
        max_results: int = 50,
        query: str | None = None,
        page_token: str | None = None,
    ) -> dict:
        """List message references (ids), not full message content."""
        params: dict[str, str] = {"maxResults": str(max_results)}
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token
        url = GMAIL_API.format(user_id=user_id)
        try:
            response = self._client.get(
                url, params=params, headers=self._auth.auth_header(), timeout=30.0
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GmailError(f"Gmail API call failed: {exc}") from exc
        return response.json()

    def get_message(
        self,
        user_id: str = "me",
        message_id: str = "",
        format: str = "full",
        metadata_headers: list[str] | None = None,
    ) -> dict:
        """Return one message in full (headers + body parts)."""
        params: dict[str, str | list[str]] = {"format": format}
        if metadata_headers:
            params["metadataHeaders"] = metadata_headers
        url = GMAIL_MESSAGE_API.format(user_id=user_id, message_id=message_id)
        try:
            response = self._client.get(
                url, params=params, headers=self._auth.auth_header(), timeout=30.0
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GmailError(f"Gmail API call failed: {exc}") from exc
        return response.json()

    def _reply_headers(self, reply_to_google_id: str, user_id: str) -> tuple[str, str] | None:
        """(Message-ID, References) of the message being answered, or None if unavailable."""
        try:
            original = self.get_message(
                user_id, reply_to_google_id, format="metadata",
                metadata_headers=["Message-ID", "References"],
            )
        except GmailError as exc:
            logger.warning("could not read headers of the message being answered: %s", exc)
            return None
        headers = {k.lower(): v for k, v in extract_headers(original).items()}
        message_id = headers.get("message-id", "").strip()
        if not message_id:
            return None
        return message_id, headers.get("references", "").strip()

    def send_message(
        self,
        to_addrs: list[str],
        subject: str,
        body: str,
        user_id: str = "me",
        thread_id: str | None = None,
        reply_to_google_id: str | None = None,
    ) -> dict:
        """Send a plain-text email (users.messages.send; needs gmail.compose/send scope).

        For a reply, ``thread_id`` puts the message in the thread and the original's
        Message-ID goes into In-Reply-To/References; Gmail also needs a matching subject
        (Gmail API threads guide).
        """
        message = EmailMessage()
        message["To"] = ", ".join(to_addrs)
        message["Subject"] = subject
        if reply_to_google_id:
            ids = self._reply_headers(reply_to_google_id, user_id)
            if ids is not None:
                message["In-Reply-To"] = ids[0]
                message["References"] = f"{ids[1]} {ids[0]}".strip()
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        payload: dict[str, str] = {"raw": raw}
        if thread_id:
            payload["threadId"] = thread_id
        url = GMAIL_SEND_API.format(user_id=user_id)
        try:
            response = self._client.post(
                url, json=payload, headers=self._auth.auth_header(), timeout=30.0
            )
            if response.status_code in (401, 403):
                raise GmailPermissionError(
                    f"Gmail refused the send (HTTP {response.status_code})"
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GmailError(f"Gmail API call failed: {exc}") from exc
        return response.json()


def extract_headers(message: dict) -> dict[str, str]:
    """Return {header name: value} for the message headers."""
    headers: dict[str, str] = {}
    for h in (message.get("payload", {}) or {}).get("headers", []) or []:
        headers[h.get("name", "")] = h.get("value", "")
    return headers


def extract_body(message: dict) -> str:
    """Best-effort extraction of the (first) plain-text body."""
    payload = message.get("payload", {}) or {}
    body = payload.get("body") or {}
    if body.get("data"):
        return _decode_b64(body["data"])
    for part in (payload.get("parts") or []) or []:
        part_body = part.get("body") or {}
        if part_body.get("data"):
            return _decode_b64(part_body["data"])
    return ""


def _decode_b64(data: str) -> str:
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
