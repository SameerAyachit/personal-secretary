"""Google OAuth2 access-token management (plan §10.6).

A refresh token is kept in Credential Manager (keyring service "Secretary",
key ``google_token``); access tokens are obtained from Google's OAuth2 token
endpoint and kept in memory. The interactive consent flow that creates the
refresh token is human-gated (credentials.json + Google Cloud project) and is
not part of this module.
"""

from __future__ import annotations

import time

import httpx

from secretary.secrets import get_secret

TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REFRESH_TOKEN_KEY = "google_token"
_REFRESH_LEEWAY_SECONDS = 60


class GoogleAuthError(Exception):
    """Raised when Google OAuth2 tokens cannot be obtained or refreshed."""


class GoogleAuth:
    """OAuth2 refresh-token holder: access_token() refreshes on demand."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        client: httpx.Client | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._client = client or httpx.Client()
        self._access_token: str | None = None
        self._expires_at: float = 0.0

    # ------------------------------------------------------------------ refresh token (Credential Manager)

    def load_refresh_token(self) -> str | None:
        """Return the stored refresh token, or None if Google isn't connected."""
        return get_secret(REFRESH_TOKEN_KEY)

    # ------------------------------------------------------------------ access token

    def access_token(self) -> str:
        """Return a valid access token, refreshing via the token endpoint if needed."""
        if self._access_token is not None and time.time() < self._expires_at - _REFRESH_LEEWAY_SECONDS:
            return self._access_token
        return self._refresh()

    def auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token()}"}

    def _refresh(self) -> str:
        if not self.load_refresh_token():
            raise GoogleAuthError("no Google refresh token; connect Google in Settings first")
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.load_refresh_token(),
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        try:
            response = self._client.post(TOKEN_ENDPOINT, data=data, timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GoogleAuthError(f"Google token refresh failed: {exc}") from exc
        payload = response.json()
        self._access_token = payload["access_token"]
        self._expires_at = time.time() + float(payload.get("expires_in", 3600))
        return self._access_token
