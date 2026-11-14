"""Google OAuth2 auth: token endpoint mocked with respx, keyring faked."""
from __future__ import annotations

import httpx

import secretary.integrations.google.auth as auth_module
from secretary.integrations.google.auth import GoogleAuth, GoogleAuthError


def _mock_token_route(respx_mock, status: int = 200, payload: dict | None = None):
    return respx_mock.post(auth_module.TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(status, json=payload or {})
    )


def test_access_token_refreshes_once_then_caches(respx_mock, monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr(auth_module, "get_secret", store.get)
    store["google_token"] = "refresh-123"

    _mock_token_route(respx_mock, payload={"access_token": "at-1", "expires_in": 3600})
    auth = GoogleAuth("cid", "secret")

    assert auth.access_token() == "at-1"
    assert auth.access_token() == "at-1"  # cached, no second HTTP call


def test_access_token_refreshes_after_expiry(respx_mock, monkeypatch):
    monkeypatch.setattr(auth_module, "get_secret", lambda key: "refresh-123")


    route = _mock_token_route(respx_mock, payload={"access_token": "at-1", "expires_in": 3600})
    auth = GoogleAuth("cid", "secret")
    auth.access_token()
    auth._expires_at = 0  # force a refresh
    assert auth.access_token() == "at-1"
    assert route.call_count == 2


def test_no_refresh_token_raises(respx_mock, monkeypatch):
    monkeypatch.setattr(auth_module, "get_secret", lambda key: None)
    route = _mock_token_route(respx_mock)


    auth = GoogleAuth("cid", "secret")
    try:
        auth.access_token()
    except GoogleAuthError as exc:
        assert "refresh token" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected GoogleAuthError")
    assert route.call_count == 0


def test_refresh_failure_raises(respx_mock, monkeypatch):
    monkeypatch.setattr(auth_module, "get_secret", lambda key: "refresh-123")
    _mock_token_route(respx_mock, status=400, payload={"error": "invalid_grant"})


    auth = GoogleAuth("cid", "secret")
    try:
        auth.access_token()
    except GoogleAuthError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("expected GoogleAuthError")
