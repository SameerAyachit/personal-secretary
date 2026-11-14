"""Build the Gmail and Calendar clients from ``credentials.json`` (plan §13).

Single place that parses the OAuth client credentials; used at startup and
whenever the user connects Google, so a restart is never required.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from secretary.integrations.google.auth import GoogleAuth
from secretary.integrations.google.calendar import CalendarClient
from secretary.integrations.google.gmail import GmailClient
from secretary.integrations.google.oauth import connected

logger = logging.getLogger(__name__)


def load_client_credentials(path: Path) -> tuple[str, str]:
    """Return ``(client_id, client_secret)`` from a Google credentials file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    installed = data.get("installed") or data.get("web") or {}
    return installed.get("client_id", ""), installed.get("client_secret", "")


def build_clients(credentials_file: Path) -> tuple[GmailClient | None, CalendarClient | None]:
    """Return ``(gmail, calendar)``, or ``(None, None)`` when Google isn't usable.

    Never raises: a broken credentials file must not break startup or the UI.
    """
    if not connected() or not credentials_file.exists():
        return None, None
    try:
        client_id, client_secret = load_client_credentials(credentials_file)
        auth = GoogleAuth(client_id, client_secret)
        return GmailClient(auth), CalendarClient(auth)
    except Exception as exc:
        logger.warning("Google clients unavailable: %s", exc)
        return None, None
