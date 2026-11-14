"""E2E: Google OAuth connect flow through the real composition root.

Reproduces: after the browser shows "you can close this tab", the app stays
"not connected" and diagnose shows the Google refresh token missing.

The flow: credentials.json -> Settings "Connect Google" ->
GoogleOAuthFlow.run() (loopback redirect + PKCE + token endpoint) ->
refresh token stored in Credential Manager -> google_connected.emit() ->
SettingsView.refresh_google() -> controller.get_google_connected() -> True.
"""
from __future__ import annotations

import os
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from secretary.controller import Controller
from secretary.integrations.google.oauth import (
    AUTH_URI,
    CLIENT_ID_KEY,
    REFRESH_TOKEN_KEY,
    TOKEN_URI,
)
from secretary.secrets import delete_secret
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate


def _conn(tmp_path: Path) -> Connection:
    db = tmp_path / "g.db"
    conn = Connection(db)
    migrate(conn._con, migrations_folder(), lambda: None)
    return conn


def _write_credentials(tmp_path: Path, client_id="cid", client_secret="secret") -> Path:
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
    p.write_text(__import__("json").dumps(data), encoding="utf-8")
    return p


def test_google_connect_stores_token_and_updates_controller(
    monkeypatch, tmp_path, respx_mock
):
    """Real flow: mocked token endpoint + real loopback redirect hit.

    After the flow, controller.get_google_connected() must be True (the refresh
    token was stored under the exact name diagnose checks).
    """
    os.environ["SECRETARY_DATA_ROOT"] = str(tmp_path)
    creds_path = _write_credentials(tmp_path)
    monkeypatch.setenv("SECRETARY_CREDENTIALS", str(creds_path))

    respx_mock.post(TOKEN_URI).mock(
        return_value=httpx.Response(
            200,
            json={
                "refresh_token": "rt-real-123",
                "access_token": "at-1",
                "expires_in": 3600,
            },
        )
    )

    def fake_open(url):
        """Simulate the browser: hit the loopback redirect with an auth code."""
        params = parse_qs(urlparse(url).query)
        redirect_uri = unquote(params.get("redirect_uri", [""])[0])
        port = urlparse(redirect_uri).port
        state = params["state"][0]

        def hit():
            time.sleep(0.2)
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/?code=auth-code&state={state}", timeout=5
            )

        threading.Thread(target=hit, daemon=True).start()

    monkeypatch.setattr("webbrowser.open", fake_open)

    conn = _conn(tmp_path)
    controller = Controller(conn)

    try:
        controller.connect_google()

        # Wait for the background thread to complete the flow.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not controller.get_google_connected():
            time.sleep(0.05)

        assert controller.get_google_connected() is True, "Google not connected after OAuth flow"
    finally:
        # Do not leave fake credentials in Credential Manager after the test.
        delete_secret(REFRESH_TOKEN_KEY)
        delete_secret(CLIENT_ID_KEY)
