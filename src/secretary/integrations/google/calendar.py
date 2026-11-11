"""Google Calendar read sync with nextSyncToken (plan §10.6, §14).

Windowed sync of ``events.list`` into the local events repo. All HTTP goes
through ``GoogleAuth`` (refresh handled there); tests mock httpx with respx, so
no real Google credentials are needed. The OAuth consent flow itself remains
human-gated.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from secretary.integrations.google.auth import GoogleAuth
from secretary.store.db import Connection
from secretary.store.repos import events as events_repo
from secretary.store.repos import settings as settings_repo

CALENDAR_API = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
SYNC_TOKEN_KEY = "google_sync_token"
_DEFAULT_TZ = "Asia/Kolkata"


class GoogleCalendarError(Exception):
    """Raised when a Calendar API call fails.

    Carries the HTTP status and Google's error reason/message (never tokens)
    so the UI can show distinct, actionable messages.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        reason: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.reason = reason or ""
        self._message = message
        super().__init__(message)

    @property
    def message(self) -> str:
        return self._message

    def user_message(self) -> str:
        """User-facing message for the Settings sync chip (no tokens)."""
        reasons = {r.strip() for r in self.reason.split(",") if r.strip()}
        if "accessNotConfigured" in reasons:
            return (
                "Google Calendar API is not enabled for this project. "
                "Enable it in the Google Cloud Console, then re-connect Google."
            )
        if "insufficientPermissions" in reasons:
            return (
                "Calendar permission missing: the connected account cannot access "
                "calendar.events. Re-connect Google in Settings to consent again."
            )
        if self.status_code is not None:
            return f"Calendar sync failed: HTTP {self.status_code}" + (
                f" — {self._message}" if self._message else ""
            )
        return f"Calendar sync failed: {self._message}"


class GoogleCalendarSyncTokenInvalid(GoogleCalendarError):
    """Raised when the nextSyncToken is invalid (HTTP 410); a full resync is required."""


class CalendarClient:
    """Thin client over Google Calendar v3 ``events.list`` (calendarId ``primary`` only)."""

    def __init__(self, auth: GoogleAuth, client: httpx.Client | None = None) -> None:
        self._auth = auth
        self._client = client or httpx.Client()

    @staticmethod
    def _parse_google_error(response: httpx.Response) -> tuple[str, str]:
        """Return (reason, message) from Google's error JSON body; never tokens."""
        reason = ""
        message = ""
        try:
            body = response.json()
            err = body.get("error", {}) if isinstance(body, dict) else {}
            message = str(err.get("message", ""))
            errors = err.get("errors", [])
            if isinstance(errors, list):
                reason = ", ".join(
                    str(e.get("reason", "")) for e in errors if isinstance(e, dict)
                )
        except Exception:  # body parsing is best-effort
            pass
        return reason, message

    def list_events(
        self,
        calendar_id: str,
        time_min: str | None = None,
        time_max: str | None = None,
        page_token: str | None = None,
        sync_token: str | None = None,
    ) -> dict:
        params: dict[str, str] = {"maxResults": "2500"}
        if sync_token:
            params["syncToken"] = sync_token
        else:
            if time_min is None or time_max is None:
                raise ValueError("time_min and time_max are required without sync_token")
            params["timeMin"] = time_min
            params["timeMax"] = time_max
            params["singleEvents"] = "true"
        if page_token:
            params["pageToken"] = page_token
        url = CALENDAR_API.format(calendar_id=calendar_id)
        try:
            response = self._client.get(
                url, params=params, headers=self._auth.auth_header(), timeout=30.0
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 410:
                raise GoogleCalendarSyncTokenInvalid(
                    "nextSyncToken is invalid; full resync required"
                ) from exc
            reason, message = self._parse_google_error(exc.response)
            status_code = exc.response.status_code
            detail = f"HTTP {status_code}" + (
                f" {reason}" if reason else ""
            ) + (f": {message}" if message else "")
            raise GoogleCalendarError(
                f"Calendar API call failed: {detail}",
                status_code=status_code,
                reason=reason,
            ) from exc
        except httpx.HTTPError as exc:
            raise GoogleCalendarError(f"Calendar API call failed: {exc}") from exc
        return response.json()


def _parse_times(item: dict) -> tuple[str, str, int]:
    """Return (start_at_iso, end_at_iso, all_day) for a Calendar API event."""
    start = item.get("start", {}) or {}
    end = item.get("end", {}) or {}
    if "date" in start:  # all-day event
        day = datetime.fromisoformat(start["date"]).date()
        zone = ZoneInfo(start.get("timeZone", _DEFAULT_TZ))
        start_local = datetime(day.year, day.month, day.day, tzinfo=zone)
        end_local = start_local + timedelta(days=1)
        return start_local.astimezone(UTC).isoformat(), end_local.astimezone(UTC).isoformat(), 1
    start_raw = start.get("dateTime", "")
    end_raw = end.get("dateTime", "")
    start_at = _to_utc(start_raw)
    end_at = _to_utc(end_raw) if end_raw else start_at
    return start_at, end_at, 0


def _to_utc(value: str) -> str:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _upsert_event(conn: Connection, item: dict, turn_id: str) -> str:
    """Insert or update one event by google_event_id; return the event id."""
    google_event_id = item["id"]
    start_at, end_at, all_day = _parse_times(item)
    fields = {
        "title": item.get("summary") or "(no title)",
        "start_at": start_at,
        "end_at": end_at,
        "tz": (item.get("start") or {}).get("timeZone", _DEFAULT_TZ),
        "all_day": all_day,
        "location": item.get("location"),
        "notes": item.get("description"),
        "etag": item.get("etag"),
    }
    row = conn.execute("SELECT id, etag FROM events WHERE google_event_id=?", (google_event_id,)).fetchone()
    if row:
        # Skip the write when the etag is unchanged (no-op sync for this event).
        if row[1] is not None and row[1] == fields.get("etag"):
            return None
        events_repo.update(conn, row[0], turn_id=turn_id, **fields)
        return str(row[0])
    fields["google_event_id"] = google_event_id
    return str(events_repo.create(conn, turn_id=turn_id, **fields))


def _soft_delete(conn: Connection, google_event_id: str, turn_id: str) -> None:
    conn.execute(
        "UPDATE events SET deleted_at=?, updated_at=? WHERE google_event_id=? AND deleted_at IS NULL",
        (_now_utc(), _now_utc(), google_event_id),
    )


def _now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sync_calendar(
    conn: Connection,
    client: CalendarClient,
    calendar_id: str,
    window_past_days: int = 7,
    window_future_days: int = 60,
    turn_id: str = "google-sync",
) -> dict:
    """Sync one window of Google Calendar events into the local store.

    Full sync (no stored sync token) uses [now - past, now + future].
    Incremental sync uses the stored nextSyncToken and applies updates and
    deletions. Returns counts.
    """
    now = datetime.now(UTC)
    time_min = (now - timedelta(days=window_past_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    time_max = (now + timedelta(days=window_future_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    sync_token = settings_repo.get(conn, SYNC_TOKEN_KEY)
    page_token = None
    synced = deleted = 0
    retried = False
    try:
        while True:
            try:
                data = client.list_events(
                    calendar_id,
                    None if sync_token else time_min,
                    None if sync_token else time_max,
                    page_token=page_token,
                    sync_token=sync_token if page_token is None else None,
                )
            except GoogleCalendarSyncTokenInvalid:
                if retried:
                    raise
                # Stale sync token: discard it and do a full time-window resync.
                retried = True
                sync_token = None
                page_token = None
                continue
            for item in data.get("items", []) or []:
                if item.get("status") == "deleted":
                    _soft_delete(conn, item["id"], turn_id)
                    deleted += 1
                else:
                    result = _upsert_event(conn, item, turn_id)
                    if result is not None:
                        synced += 1
            page_token = data.get("nextPageToken")
            next_sync_token = data.get("nextSyncToken")
            if next_sync_token:
                sync_token = next_sync_token
            if not page_token:
                break
        settings_repo.set(conn, SYNC_TOKEN_KEY, sync_token or "", turn_id=turn_id)
        # Sync succeeded: clear any previous failure flag.
        settings_repo.set(conn, "google_sync_failed", "0", turn_id=turn_id)
        settings_repo.set(conn, "google_sync_error", "", turn_id=turn_id)
    except GoogleCalendarSyncTokenInvalid:
        raise
    except GoogleCalendarError as exc:  # distinct user message for 403s etc.
        settings_repo.set(conn, "google_sync_failed", "1", turn_id=turn_id)
        settings_repo.set(conn, "google_sync_error", exc.user_message(), turn_id=turn_id)
        raise
    except Exception as exc:
        # Record the failure so the UI can show a "sync failed" chip.
        settings_repo.set(conn, "google_sync_failed", "1", turn_id=turn_id)
        settings_repo.set(conn, "google_sync_error", str(exc), turn_id=turn_id)
        raise
    return {"synced": synced, "deleted": deleted}
