"""Google OAuth2 consent flow via loopback redirect + PKCE (plan §13.2).

Desktop (installed app) OAuth: open the system browser on the Google consent
URL, listen for the redirect on an ephemeral loopback port, then exchange the
authorization code for tokens. The refresh token is stored in Credential
Manager; access tokens are rebuilt lazily by :class:`GoogleAuth`.

Implemented with ``httpx`` + the standard library (no ``google-auth-oauthlib``
dependency) so the flow is fully testable with respx-mocked HTTP.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets as _secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from secretary.secrets import delete_secret, get_secret, set_secret

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
# Plan §13.1: narrowest scopes — Calendar events read/write, Gmail read-only,
# Gmail compose (drafts). Send is opt-in at Phase 3.5.
SCOPES = (
    "https://www.googleapis.com/auth/calendar.events "
    "https://www.googleapis.com/auth/gmail.readonly "
    "https://www.googleapis.com/auth/gmail.compose"
)
REFRESH_TOKEN_KEY = "google_token"
CLIENT_ID_KEY = "google_client_id"

logger = logging.getLogger(__name__)


class GoogleOAuthError(Exception):
    """Raised when the OAuth consent flow or token exchange fails."""


def is_invalid_grant(exc: BaseException) -> bool:
    """True if an OAuth/token failure is an OAuth ``invalid_grant``."""
    return "invalid_grant" in str(exc)


class _RedirectHandler(BaseHTTPRequestHandler):
    """Captures the ``?code=...`` (or ``?error=...``) from the loopback redirect.

    Stores results on the server instance (not class-level) so each flow has
    its own state; only one flow runs at a time (plan D14). Non-redirect
    requests (favicon, etc.) are ignored.
    """

    def do_GET(self):  # http.server override name
        params = parse_qs(urlparse(self.path).query)
        server = self.server
        # Ignore requests that are not the OAuth redirect (favicon, etc.).
        if "code" not in params and "error" not in params:
            self.send_response(404)
            self.end_headers()
            return
        if "code" in params:
            server._handler_code = params["code"][0]
            server._handler_error = None
            server._handler_error_description = None
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"Authorization complete. You can close this window."
            )
        else:
            server._handler_error = params.get("error", ["unknown"])[0]
            descs = params.get("error_description", [])
            server._handler_error_description = descs[0] if descs else ""
            self.send_response(400)
            self.end_headers()

    def log_message(self, fmt: str, *args) -> None:  # silence
        return


class GoogleOAuthFlow:
    """Run the installed-app OAuth consent flow and store the refresh token.

    One flow at a time (plan D14): per-flow state in the handler instance,
    state parameter verified, non-redirect requests ignored, Google's error
    and error_description included in failures, browser opened once.
    """

    _flow_running = False

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        auth_uri: str,
        token_uri: str,
        redirect_uri: str,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.auth_uri = auth_uri
        self.token_uri = token_uri
        self.redirect_uri = redirect_uri

    @classmethod
    def from_credentials_file(cls, path) -> GoogleOAuthFlow:
        """Build a flow from a Google ``credentials.json`` file."""
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        installed = data.get("installed") or data.get("web") or {}
        client_id = installed["client_id"]
        client_secret = installed.get("client_secret", "")
        auth_uri = installed.get("auth_uri", AUTH_URI)
        token_uri = installed.get("token_uri", TOKEN_URI)
        redirect_uris = installed.get("redirect_uris", ["http://localhost"])
        redirect_uri = redirect_uris[0] if redirect_uris else "http://localhost"
        return cls(client_id, client_secret, auth_uri, token_uri, redirect_uri)

    # ---------------------------------------------------------------- PKCE

    @staticmethod
    def _make_pkce_pair() -> tuple[str, str]:
        code_verifier = _secrets.token_urlsafe(32)
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return code_verifier, code_challenge

    def authorization_url(
        self, state: str, code_challenge: str, redirect_uri: str | None = None
    ) -> str:
        redirect_uri = redirect_uri or self.redirect_uri
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "response_type": "code",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{self.auth_uri}?{urlencode(params)}"

    # ---------------------------------------------------------------- token exchange

    def exchange_code(
        self, code: str, code_verifier: str, redirect_uri: str | None = None
    ) -> dict[str, Any]:
        redirect_uri = redirect_uri or self.redirect_uri
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code_verifier": code_verifier,
        }
        try:
            response = httpx.post(self.token_uri, data=data, timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = ""
            try:
                err = exc.response.json().get("error", {})
                body = f"{err.get('error','')} {err.get('error_description','')}".strip()
            except Exception:
                pass
            raise GoogleOAuthError(
                f"token exchange failed: {exc} {body}".strip()
            ) from exc
        return response.json()

    # ---------------------------------------------------------------- loopback server

    @staticmethod
    def _pick_port() -> int:
        with HTTPServer(("127.0.0.1", 0), _RedirectHandler) as server:
            return server.server_address[1]

    def _run_server(self, port: int) -> str:
        server = HTTPServer(("127.0.0.1", port), _RedirectHandler)
        server._handler_code = None
        server._handler_error = None
        server._handler_error_description = None
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            # Wait for the redirect handler to capture the code (or an error).
            # 3-minute timeout (plan D14).
            deadline = time.time() + 180
            while (
                server._handler_code is None and server._handler_error is None
            ):
                if time.time() > deadline:
                    raise GoogleOAuthError("OAuth flow timed out waiting for redirect")
                time.sleep(0.05)
            handler_error = server._handler_error
            handler_error_desc = server._handler_error_description or ""
            if handler_error:
                raise GoogleOAuthError(
                    f"OAuth flow failed: {handler_error} {handler_error_desc}".strip()
                )
            handler_code = server._handler_code
            if not handler_code:
                raise GoogleOAuthError("OAuth flow returned no authorization code")
            return handler_code
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join()

    # ---------------------------------------------------------------- run

    def run(self) -> str:
        """Run the full consent flow; return the refresh token.

        Only one flow may run at a time; the browser is opened once.
        """
        if self._flow_running:
            raise GoogleOAuthError("An OAuth flow is already in progress")
        self._flow_running = True
        try:
            logger.info("google oauth flow starting")
            port = self._pick_port()
            redirect_uri = f"http://127.0.0.1:{port}/"
            state = _secrets.token_urlsafe(16)
            code_verifier, code_challenge = self._make_pkce_pair()
            url = self.authorization_url(state, code_challenge, redirect_uri)
            logger.info("google consent url opened in browser")
            webbrowser.open(url)
            code = self._run_server(port)
            logger.info("google authorization code received")
            tokens = self.exchange_code(code, code_verifier, redirect_uri)
            refresh_token = tokens.get("refresh_token")
            if not refresh_token:
                raise GoogleOAuthError(
                    "no refresh token in token response (try prompt=consent)"
                )
            set_secret(REFRESH_TOKEN_KEY, refresh_token)
            set_secret(CLIENT_ID_KEY, self.client_id)
            if not connected():
                raise GoogleOAuthError(
                    "refresh token was not stored in Credential Manager"
                )
            logger.info("google refresh token stored in Credential Manager")
            return refresh_token
        finally:
            self._flow_running = False


def connected() -> bool:
    """True if a Google refresh token is stored in Credential Manager."""
    return get_secret(REFRESH_TOKEN_KEY) is not None


def disconnect() -> None:
    """Remove the Google refresh token (and client id) from Credential Manager."""
    delete_secret(REFRESH_TOKEN_KEY)
    delete_secret(CLIENT_ID_KEY)
