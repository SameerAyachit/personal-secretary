"""Gmail read client: Gmail API mocked with respx (no real credentials)."""
from __future__ import annotations

import base64
import email
import json

import httpx
import pytest

from secretary.integrations.google.gmail import (
    GMAIL_API,
    GMAIL_MESSAGE_API,
    GMAIL_SEND_API,
    GmailClient,
    GmailError,
    GmailPermissionError,
    extract_body,
    extract_headers,
)


class _FakeAuth:
    """Minimal stand-in for GoogleAuth providing an auth header."""

    def auth_header(self):
        return {"Authorization": "Bearer fake-token"}


def test_list_messages_returns_message_refs(respx_mock):
    route = respx_mock.get(GMAIL_API.format(user_id="me")).mock(
        return_value=httpx.Response(
            200,
            json={
                "messages": [
                    {"id": "msg-1", "threadId": "thread-1"},
                    {"id": "msg-2", "threadId": "thread-2"},
                ],
                "nextPageToken": None,
                "resultSizeEstimate": 2,
            },
        )
    )
    client = GmailClient(_FakeAuth())
    result = client.list_messages(max_results=5)
    assert [m["id"] for m in result["messages"]] == ["msg-1", "msg-2"]
    req = route.calls[0].request
    assert req.url.params["maxResults"] == "5"
    client._client.close()


def test_get_message_returns_full_message(respx_mock):
    message = {
        "id": "msg-1",
        "threadId": "thread-1",
        "payload": {
            "headers": [
                {"name": "From", "value": "alice@example.com"},
                {"name": "Subject", "value": "Hello"},
                {"name": "Date", "value": "Mon, 09 Nov 2026 10:00:00 +0000"},
            ],
            "body": {"data": "SGVsbG8gd29ybGQ="},  # "Hello world"
            "mimeType": "text/plain",
        },
    }
    respx_mock.get(
        GMAIL_MESSAGE_API.format(user_id="me", message_id="msg-1")
    ).mock(return_value=httpx.Response(200, json=message))

    client = GmailClient(_FakeAuth())
    result = client.get_message("me", "msg-1")
    assert result["id"] == "msg-1"
    assert extract_headers(result)["From"] == "alice@example.com"
    assert extract_headers(result)["Subject"] == "Hello"
    assert extract_body(result) == "Hello world"
    client._client.close()


def test_extract_body_multipart():
    message = {
        "payload": {
            "parts": [
                {"body": {"data": "VGhlIHRleHQ="}},  # "The text"
                {"body": {"data": "PGRpdj5UaGUgSFRNTTwvZGlkPg=="}},  # HTML part
            ]
        }
    }
    assert extract_body(message) == "The text"


def test_get_message_error(respx_mock):
    respx_mock.get(
        GMAIL_MESSAGE_API.format(user_id="me", message_id="missing")
    ).mock(return_value=httpx.Response(404, json={"error": {"message": "Not found"}}))
    client = GmailClient(_FakeAuth())
    try:
        client.get_message("me", "missing")
    except GmailError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("expected GmailError")
    client._client.close()


def test_send_message_posts_base64url_rfc2822(respx_mock):
    route = respx_mock.post(GMAIL_SEND_API.format(user_id="me")).mock(
        return_value=httpx.Response(200, json={"id": "sent-1", "threadId": "t-1"})
    )
    client = GmailClient(_FakeAuth())
    result = client.send_message(["ravi@example.com", "x@example.com"], "Hi there", "Body text")
    assert result["id"] == "sent-1"
    req = route.calls[0].request
    assert req.headers["Authorization"] == "Bearer fake-token"
    raw = json.loads(req.content)["raw"]
    assert "=" not in raw or raw.endswith("=")  # base64url, padding tolerated
    parsed = email.message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    assert parsed["To"] == "ravi@example.com, x@example.com"
    assert parsed["Subject"] == "Hi there"
    assert parsed.get_payload(decode=True).decode().strip() == "Body text"


def test_send_message_403_is_permission_error(respx_mock):
    respx_mock.post(GMAIL_SEND_API.format(user_id="me")).mock(
        return_value=httpx.Response(403, json={"error": {"message": "insufficient"}})
    )
    with pytest.raises(GmailPermissionError):
        GmailClient(_FakeAuth()).send_message(["a@b.com"], "s", "b")


def test_send_message_other_failure_is_gmail_error(respx_mock):
    respx_mock.post(GMAIL_SEND_API.format(user_id="me")).mock(return_value=httpx.Response(500))
    with pytest.raises(GmailError):
        GmailClient(_FakeAuth()).send_message(["a@b.com"], "s", "b")
