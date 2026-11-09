"""Google OAuth consent flow: loopback redirect + PKCE, token endpoint mocked with respx."""
from __future__ import annotations

import json

import httpx

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
    monkeypatch.setattr(oauth_module, "delete_secret", store.pop)

    flow = GoogleOAuthFlow.from_credentials_file(creds)
    monkeypatch.setattr(flow, "_run_server", lambda port: "auth-code")
    monkeypatch.setattr(oauth_module.webbrowser, "open", lambda url: None)

    rt = flow.run()
    assert rt == "rt-abc"
    assert store.get(oauth_module.REFRESH_TOKEN_KEY) == "rt-abc"


def test_run_no_refresh_token_raises(respx_mock, monkeypatch, tmp_path):
    creds = _write_credentials(tmp_path)
    _mock_token_route(respx_mock, payload={"access_token": "at-1"})

    flow = GoogleOAuthFlow.from_credentials_file(creds)
    monkeypatch.setattr(flow, "_run_server", lambda port: "auth-code")
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
