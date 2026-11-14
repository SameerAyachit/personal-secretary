"""Google OAuth consent flow: loopback redirect + PKCE, token endpoint mocked with respx."""
from __future__ import annotations

import contextlib
import json
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest

import secretary.integrations.google.oauth as oauth_module
from secretary.integrations.google.oauth import (
    AUTH_URI,
    TOKEN_URI,
    GoogleOAuthError,
    GoogleOAuthFlow,
    connected,
    disconnect,
    is_invalid_grant,
)


def _write_credentials(tmp_path, client_id="cid", client_secret="secret"):
    data = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["http://localhost"],
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI,
        }
    }
    p = tmp_path / "credentials.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _mock_token_route(respx_mock, status: int = 200, payload: dict | None = None):
    return respx_mock.post(TOKEN_URI).mock(
        return_value=httpx.Response(status, json=payload or {})
    )


def test_authorization_url_contains_pkce_and_scopes():
    flow = GoogleOAuthFlow(
        "cid", "secret", AUTH_URI, TOKEN_URI, "http://127.0.0.1:1234/"
    )
    url = flow.authorization_url("state-1", "challenge-1")
    assert "client_id=cid" in url
    assert "scope=" in url
    assert "calendar.events" in url
    assert "gmail.readonly" in url
    assert "gmail.compose" in url
    assert "response_type=code" in url
    assert "code_challenge=challenge-1" in url
    assert "code_challenge_method=S256" in url
    assert "state=state-1" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url


def test_exchange_code_returns_refresh_token(respx_mock):
    _mock_token_route(
        respx_mock,
        payload={"refresh_token": "rt-abc", "access_token": "at-1", "expires_in": 3600},
    )
    flow = GoogleOAuthFlow("cid", "secret", AUTH_URI, TOKEN_URI, "http://localhost")
    tokens = flow.exchange_code("auth-code", "verifier-1")
    assert tokens["refresh_token"] == "rt-abc"
    assert tokens["access_token"] == "at-1"


def test_exchange_code_failure_raises(respx_mock):
    _mock_token_route(respx_mock, status=400, payload={"error": "invalid_grant"})
    flow = GoogleOAuthFlow("cid", "secret", AUTH_URI, TOKEN_URI, "http://localhost")
    try:
        flow.exchange_code("auth-code", "verifier-1")
    except GoogleOAuthError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("expected GoogleOAuthError")


def test_run_stores_refresh_token(respx_mock, monkeypatch, tmp_path):
    creds = _write_credentials(tmp_path)
    _mock_token_route(respx_mock, payload={"refresh_token": "rt-abc"})

    store: dict[str, str] = {}
    monkeypatch.setattr(oauth_module, "set_secret", store.__setitem__)
    monkeypatch.setattr(oauth_module, "get_secret", store.get)
    monkeypatch.setattr(oauth_module, "delete_secret", store.pop)

    flow = GoogleOAuthFlow.from_credentials_file(creds)
    monkeypatch.setattr(flow, "_run_server", lambda port, state=None: "auth-code")
    monkeypatch.setattr(oauth_module.webbrowser, "open", lambda url: None)

    rt = flow.run()
    assert rt == "rt-abc"
    assert store.get(oauth_module.REFRESH_TOKEN_KEY) == "rt-abc"


def test_run_no_refresh_token_raises(respx_mock, monkeypatch, tmp_path):
    creds = _write_credentials(tmp_path)
    _mock_token_route(respx_mock, payload={"access_token": "at-1"})

    flow = GoogleOAuthFlow.from_credentials_file(creds)
    monkeypatch.setattr(flow, "_run_server", lambda port, state=None: "auth-code")
    monkeypatch.setattr(oauth_module.webbrowser, "open", lambda url: None)

    try:
        flow.run()
    except GoogleOAuthError as exc:
        assert "no refresh token" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected GoogleOAuthError")


def test_connected_and_disconnect(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr(oauth_module, "get_secret", store.get)
    monkeypatch.setattr(oauth_module, "set_secret", store.__setitem__)
    monkeypatch.setattr(oauth_module, "delete_secret", lambda key: store.pop(key, None))

    assert not connected()
    disconnect()  # must not raise when nothing stored
    assert not connected()

    oauth_module.set_secret(oauth_module.REFRESH_TOKEN_KEY, "rt-abc")
    assert connected()
    disconnect()
    assert not connected()


def test_is_invalid_grant():
    assert is_invalid_grant(GoogleOAuthError("token exchange failed: invalid_grant"))
    assert is_invalid_grant(ValueError("invalid_grant"))
    assert not is_invalid_grant(GoogleOAuthError("network down"))


def test_full_flow_real_loopback_stores_refresh_token(respx_mock, monkeypatch, tmp_path):
    """Reproduce the real sign-in flow: mocked token endpoint + real loopback hit.

    Simulates the browser being redirected back to the ephemeral loopback port
    with an authorization code, then verifies the refresh token is stored under
    the exact name diagnose checks (``google_token``).
    """
    creds = _write_credentials(tmp_path)
    _mock_token_route(
        respx_mock,
        payload={"refresh_token": "rt-real-123", "access_token": "at-1", "expires_in": 3600},
    )

    store: dict[str, str] = {}
    monkeypatch.setattr(oauth_module, "set_secret", store.__setitem__)
    monkeypatch.setattr(oauth_module, "delete_secret", lambda key: store.pop(key, None))
    monkeypatch.setattr(oauth_module, "get_secret", store.get)

    flow = GoogleOAuthFlow.from_credentials_file(creds)

    # Simulate the browser: open() is called with the Google auth URL; the
    # loopback port is carried in the ``redirect_uri`` query parameter. Once the
    # loopback server is serving, hit it with the redirect containing the code.
    def fake_open(url):
        params = parse_qs(urlparse(url).query)
        redirect_uri = params.get("redirect_uri", [""])[0]
        port = urlparse(redirect_uri).port
        state = params["state"][0]

        def hit() -> None:
            time.sleep(0.3)
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/?code=auth-code&state={state}", timeout=5
            )

        threading.Thread(target=hit, daemon=True).start()

    monkeypatch.setattr(oauth_module.webbrowser, "open", fake_open)

    rt = flow.run()
    assert rt == "rt-real-123"
    # Token stored under the exact name diagnose checks.
    assert store.get("google_token") == "rt-real-123"
    assert store.get("google_client_id") == "cid"
    assert connected()


def test_unexpected_flow_exception_swallowed_before_fix(respx_mock, monkeypatch, tmp_path):
    """Regression: an unexpected exception in the background thread must not be
    swallowed — it must surface as a clear Settings error instead of silently
    leaving Google showing "not connected".
    """
    creds = _write_credentials(tmp_path)
    _mock_token_route(
        respx_mock,
        payload={"refresh_token": "rt-abc", "access_token": "at-1", "expires_in": 3600},
    )

    store: dict[str, str] = {}
    monkeypatch.setattr(oauth_module, "set_secret", store.__setitem__)
    monkeypatch.setattr(oauth_module, "delete_secret", lambda key: store.pop(key, None))

    flow = GoogleOAuthFlow.from_credentials_file(creds)

    # Simulate the browser redirect so _run_server() completes, then make the
    # token exchange raise an unexpected exception.
    def fake_open(url):
        params = parse_qs(urlparse(url).query)
        port = urlparse(unquote(params.get("redirect_uri", [""])[0])).port
        state = params["state"][0]

        def hit():
            time.sleep(0.3)
            urllib.request.urlopen(f"http://127.0.0.1:{port}/?code=auth-code&state={state}", timeout=5)

        threading.Thread(target=hit, daemon=True).start()

    monkeypatch.setattr(oauth_module.webbrowser, "open", fake_open)

    # Make run() raise an unexpected (non-GoogleOAuthError) exception, as a real
    # network/keyring failure would. Before the fix this escaped the daemon
    # thread and was lost; after the fix _connect_google_background catches it.
    monkeypatch.setattr(flow, "exchange_code", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    try:
        flow.run()
    except RuntimeError:
        pass  # the unexpected exception escapes run() and must be caught by the caller
    else:
        raise AssertionError("expected RuntimeError to escape run()")


def test_redirect_with_wrong_state_is_rejected(respx_mock, monkeypatch, tmp_path):
    """CSRF guard: a redirect whose state differs from ours must not yield a code."""
    creds = _write_credentials(tmp_path)
    store: dict[str, str] = {}
    monkeypatch.setattr(oauth_module, "set_secret", store.__setitem__)
    monkeypatch.setattr(oauth_module, "get_secret", store.get)
    flow = GoogleOAuthFlow.from_credentials_file(creds)

    def fake_open(url):
        params = parse_qs(urlparse(url).query)
        port = urlparse(unquote(params["redirect_uri"][0])).port

        def hit():
            time.sleep(0.2)
            with contextlib.suppress(urllib.error.HTTPError):
                urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/?code=evil-code&state=attacker", timeout=5
                )

        threading.Thread(target=hit, daemon=True).start()

    monkeypatch.setattr(oauth_module.webbrowser, "open", fake_open)
    with pytest.raises(GoogleOAuthError, match="state"):
        flow.run()
    assert not store  # nothing stored
    assert GoogleOAuthFlow._flow_running is False  # released after failure


def test_second_concurrent_flow_is_refused(monkeypatch, tmp_path):
    creds = _write_credentials(tmp_path)
    monkeypatch.setattr(GoogleOAuthFlow, "_flow_running", True)
    flow = GoogleOAuthFlow.from_credentials_file(creds)
    with pytest.raises(GoogleOAuthError, match="already in progress"):
        flow.run()
