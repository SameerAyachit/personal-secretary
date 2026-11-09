"""Safe fetch: URL rules tested with respx-mocked HTTP (plan §14.2)."""

from __future__ import annotations

import socket

import httpx

import secretary.integrations.fetch as fetch_mod
from secretary.integrations.fetch import FetchError, fetch_url

PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def _allow_public(monkeypatch):
    monkeypatch.setattr(fetch_mod.socket, "getaddrinfo", lambda host, port=None, *a, **k: PUBLIC)


def _block_private(monkeypatch):
    monkeypatch.setattr(
        fetch_mod.socket,
        "getaddrinfo",
        lambda host, port=None, *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ],
    )


def test_fetch_returns_extracted_text(respx_mock, monkeypatch):
    _allow_public(monkeypatch)
    respx_mock.get("https://example.com/page").mock(
        return_value=httpx.Response(
            200,
            text=(
                "<html><body><article>Main content here about nothing at all.</article>"
                "<nav>navigation stuff</nav></body></html>"
            ),
        )
    )
    result = fetch_url("https://example.com/page")
    assert result["url"] == "https://example.com/page"
    assert "Main content here" in result["text"]


def test_fetch_blocks_loopback(monkeypatch):
    _block_private(monkeypatch)
    try:
        fetch_url("http://127.0.0.1/secret")
    except FetchError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("expected FetchError for loopback")


def test_fetch_blocks_private(monkeypatch):
    _block_private(monkeypatch)
    try:
        fetch_url("http://192.168.1.1/secret")
    except FetchError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("expected FetchError for private address")


def test_fetch_blocks_link_local(monkeypatch):
    monkeypatch.setattr(
        fetch_mod.socket,
        "getaddrinfo",
        lambda host, port=None, *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))
        ],
    )
    try:
        fetch_url("http://169.254.169.254/")
    except FetchError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("expected FetchError for link-local address")


def test_fetch_blocks_redirect_to_private(respx_mock, monkeypatch):
    def fake_getaddrinfo(host, port=None, *a, **k):
        if host in ("127.0.0.1", "localhost", "::1"):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, 443))]
        return PUBLIC

    monkeypatch.setattr(fetch_mod.socket, "getaddrinfo", fake_getaddrinfo)
    respx_mock.get("https://good.example.com/").mock(
        return_value=httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
    )
    respx_mock.get("http://127.0.0.1/private").mock(
        return_value=httpx.Response(200, text="<html><body>private</body></html>")
    )
    try:
        fetch_url("https://good.example.com/")
    except FetchError as exc:
        assert "redirect to 127.0.0.1 is not allowed" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected FetchError for redirect to private")


def test_fetch_blocks_json_content_type(respx_mock, monkeypatch):
    _allow_public(monkeypatch)
    respx_mock.get("https://example.com/data.json").mock(
        return_value=httpx.Response(200, content=b'{"ok": true}', headers={"content-type": "application/json"})
    )
    try:
        fetch_url("https://example.com/data.json")
    except FetchError as exc:
        assert "content type" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected FetchError for JSON content type")


def test_fetch_blocks_non_http_url():
    try:
        fetch_url("ftp://example.com/file")
    except FetchError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("expected FetchError for ftp URL")


def test_fetch_enforces_size_cap(respx_mock, monkeypatch):
    _allow_public(monkeypatch)
    respx_mock.get("https://example.com/big").mock(
        return_value=httpx.Response(200, text="x" * 100)
    )
    monkeypatch.setattr(fetch_mod, "MAX_BYTES", 10)
    try:
        fetch_url("https://example.com/big")
    except FetchError as exc:
        assert "1 MB cap" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected FetchError for oversized response")
