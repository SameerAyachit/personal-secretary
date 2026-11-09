"""Gmail read client (plan §13.4).

Read-only access to Gmail messages. Results are untrusted data from the web;
the agent loop wraps them as ``<untrusted>`` (Section 8.6).
"""

from __future__ import annotations

import base64

import httpx

from secretary.integrations.google.auth import GoogleAuth

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/{user_id}/messages"
GMAIL_MESSAGE_API = (
    "https://gmail.googleapis.com/gmail/v1/users/{user_id}/messages/{message_id}"
)
READ_ONLY_SCOPES = "https://www.googleapis.com/auth/gmail.readonly"


class GmailError(Exception):
    """Raised when a Gmail API call fails."""


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
        self, user_id: str = "me", message_id: str = "", format: str = "full"
    ) -> dict:
        """Return one message in full (headers + body parts)."""
        params = {"format": format}
        url = GMAIL_MESSAGE_API.format(user_id=user_id, message_id=message_id)
        try:
            response = self._client.get(
                url, params=params, headers=self._auth.auth_header(), timeout=30.0
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
