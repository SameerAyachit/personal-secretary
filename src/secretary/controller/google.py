"""Google account connect/disconnect and client wiring (plan section 13)."""

from __future__ import annotations

import contextlib
import logging
import threading

from PySide6.QtCore import Slot

from secretary.integrations.google.clients import build_clients
from secretary.integrations.google.oauth import (
    GoogleOAuthError,
    GoogleOAuthFlow,
    connected,
    disconnect,
    is_invalid_grant,
)
from secretary.paths import credentials_path
from secretary.store.repos import settings as settings_repo

logger = logging.getLogger(__name__)


class GoogleMixin:
    """Google account connect/disconnect and client wiring (plan section 13)."""

    def get_google_connected(self) -> bool:
        """True if a Google refresh token is stored in Credential Manager."""
        try:
            return connected()
        except Exception:
            return False

    def get_google_sync_status(self) -> dict:
        """Return the last Google Calendar sync status for the UI chip."""
        try:
            failed = settings_repo.get(self.conn, "google_sync_failed") == "1"
            error = settings_repo.get(self.conn, "google_sync_error") or ""
            return {"failed": bool(failed), "error": str(error)}
        except Exception:
            return {"failed": False, "error": ""}

    @Slot()
    def connect_google(self) -> None:
        """Run the OAuth consent flow (credentials.json) on a background thread
        so the UI is not blocked while the user authenticates in the browser.
        """
        threading.Thread(target=self._connect_google_background, daemon=True).start()

    def _connect_google_background(self) -> None:
        """Run the OAuth consent flow on a background thread.

        Every step is logged (without secrets) and any failure is surfaced
        through the ``error`` signal so the Settings view can show a clear
        message instead of silently leaving Google "not connected".
        """
        logger.info("google connect flow started")
        try:
            creds_path = credentials_path()
            logger.info("google credentials file: %s", creds_path)
            flow = GoogleOAuthFlow.from_credentials_file(creds_path)
            logger.info("google consent flow starting (browser + loopback)")
            flow.run()
            self.rebuild_google_client()
            logger.info("google refresh token stored in Credential Manager")
        except FileNotFoundError:
            msg = (
                "credentials.json not found in the data root. "
                "Download it from the Google Cloud console and place it next to config.toml."
            )
            logger.warning("google connect: %s", msg)
            self.error.emit("google_connect", msg)
            return
        except GoogleOAuthError as exc:
            if is_invalid_grant(exc):
                disconnect()
            msg = str(exc)
            logger.warning("google connect failed: %s", msg)
            self.error.emit("google_connect", msg)
            return
        except Exception as exc:  # unexpected failure: never swallow in the daemon thread
            msg = f"google connect failed: {exc}"
            logger.exception("google connect failed unexpectedly")
            self.error.emit("google_connect", msg)
            return
        self.google_connected.emit()
        logger.info("google connect flow completed")

    @Slot()
    def disconnect_google(self) -> None:
        """Remove the Google refresh token (Reconnect Google path)."""
        with contextlib.suppress(Exception):
            disconnect()
        self.google_connected.emit()

    def rebuild_google_client(self) -> None:
        """Rebuild Gmail + Calendar clients when Google connects (no restart).

        Hands the new clients to the running scheduler so sync and event
        write-back start immediately (plan D16).
        """
        gmail, calendar = build_clients(credentials_path())
        if self._scheduler is not None:
            self._scheduler.set_google_clients(gmail, calendar)
