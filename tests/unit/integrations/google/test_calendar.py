"""Google Calendar sync: Calendar API mocked with respx (no real credentials)."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import httpx
import pytest

import secretary.integrations.google.auth as auth_module
from secretary.integrations.google.auth import GoogleAuth, GoogleAuthError
from secretary.integrations.google.calendar import (
    CalendarClient,
    GoogleCalendarError,
    GoogleCalendarSyncTokenInvalid,
    sync_calendar,
)
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import events as events_repo
from secretary.store.repos import settings as settings_repo


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "g.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


def _full_sync_page(items, next_page_token=None, next_sync_token="tok-1"):
    return {
        "kind": "calendar#events",
        "items": items,
        "nextPageToken": next_page_token,
        "nextSyncToken": next_sync_token,
    }


def test_full_sync_upserts_events_and_saves_token(respx_mock, monkeypatch):
    monkeypatch.setattr(auth_module, "get_secret", lambda key: "refresh-123")
    monkeypatch.setattr(auth_module, "set_secret", lambda key, value: None)
    monkeypatch.setattr(auth_module, "delete_secret", lambda key: None)
    respx_mock.post(auth_module.TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
    )
    route = respx_mock.get(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    ).mock(return_value=httpx.Response(200, json=_full_sync_page([
        {
            "id": "evt-1", "status": "confirmed", "etag": "etag-1",
            "summary": "Team standup",
            "start": {"dateTime": "2026-11-09T04:30:00Z", "timeZone": "Asia/Kolkata"},
            "end": {"dateTime": "2026-11-09T05:30:00Z", "timeZone": "Asia/Kolkata"},
            "location": "Conference room",
            "description": "Weekly standup",
        },
        {
            "id": "evt-2", "status": "confirmed", "etag": "etag-2",
            "summary": "Holiday",
            "start": {"date": "2026-11-10", "timeZone": "Asia/Kolkata"},
            "end": {"date": "2026-11-11", "timeZone": "Asia/Kolkata"},
        },
    ])))

    auth = GoogleAuth("cid", "secret")
    client = CalendarClient(auth)
    conn = _conn()
    try:
        result = sync_calendar(conn, client, "primary", window_past_days=7, window_future_days=60)
        assert result == {"synced": 2, "deleted": 0}

        # Request used the time window and singleEvents.
        req = route.calls[0].request
        assert "timeMin" in req.url.params and "timeMax" in req.url.params
        assert req.url.params["singleEvents"] == "true"
        assert req.url.params["maxResults"] == "2500"

        rows = events_repo.list_window(conn, start_at="2026-01-01T00:00:00+00:00", end_at="2027-01-01T00:00:00+00:00")
        assert {r["title"] for r in rows} == {"Team standup", "Holiday"}
        standup = next(r for r in rows if r["title"] == "Team standup")
        assert standup["start_at"] == "2026-11-09T04:30:00+00:00"
        assert standup["end_at"] == "2026-11-09T05:30:00+00:00"
        assert standup["tz"] == "Asia/Kolkata"
        assert standup["all_day"] == 0
        assert standup["google_event_id"] == "evt-1"
        assert standup["etag"] == "etag-1"

        holiday = next(r for r in rows if r["title"] == "Holiday")
        assert holiday["all_day"] == 1
        # Kolkata midnight on 2026-11-10 -> 18:30Z on 2026-11-09.
        assert holiday["start_at"] == "2026-11-09T18:30:00+00:00"
        assert holiday["end_at"] == "2026-11-10T18:30:00+00:00"

        assert settings_repo.get(conn, "google_sync_token") == "tok-1"
    finally:
        conn.close()


def test_incremental_sync_uses_token_and_soft_deletes(respx_mock, monkeypatch):
    # Pre-seed an event from a previous full sync.
    conn = _conn()
    try:
        events_repo.create(
            conn, title="Old event", start_at="2026-11-09T04:30:00+00:00",
            end_at="2026-11-09T05:30:00+00:00", tz="Asia/Kolkata",
            google_event_id="evt-1", etag="etag-0", turn_id="google-sync",
        )
        settings_repo.set(conn, "google_sync_token", "tok-1", turn_id="google-sync")

        monkeypatch.setattr(auth_module, "get_secret", lambda key: "refresh-123")
        monkeypatch.setattr(auth_module, "set_secret", lambda key, value: None)
        monkeypatch.setattr(auth_module, "delete_secret", lambda key: None)
        respx_mock.post(auth_module.TOKEN_ENDPOINT).mock(
            return_value=httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        )
        route = respx_mock.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        ).mock(return_value=httpx.Response(200, json=_full_sync_page([
            {"id": "evt-1", "status": "deleted"},
            {
                "id": "evt-3", "status": "confirmed", "etag": "etag-3",
                "summary": "New event",
                "start": {"dateTime": "2026-11-12T06:00:00Z", "timeZone": "Asia/Kolkata"},
                "end": {"dateTime": "2026-11-12T07:00:00Z", "timeZone": "Asia/Kolkata"},
            },
        ], next_sync_token="tok-2")))

        auth = GoogleAuth("cid", "secret")
        result = sync_calendar(conn, CalendarClient(auth), "primary")
        assert result == {"synced": 1, "deleted": 1}

        req = route.calls[0].request
        assert req.url.params["syncToken"] == "tok-1"
        assert "timeMin" not in req.url.params and "timeMax" not in req.url.params

        rows = events_repo.list_window(conn, start_at="2026-01-01T00:00:00+00:00", end_at="2027-01-01T00:00:00+00:00")
        assert [r["title"] for r in rows] == ["New event"]
        raw = conn.execute("SELECT deleted_at FROM events WHERE google_event_id=?", ("evt-1",)).fetchone()
        assert raw is not None and raw[0] is not None
        assert settings_repo.get(conn, "google_sync_token") == "tok-2"
    finally:
        conn.close()


def test_sync_requires_refresh_token(respx_mock):
    route = respx_mock.get(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    ).mock(return_value=httpx.Response(200, json={"items": []}))
    auth = GoogleAuth("cid", "secret")  # no refresh token stored
    conn = _conn()
    try:
        try:
            sync_calendar(conn, CalendarClient(auth), "primary")
        except GoogleAuthError as exc:
            assert "refresh token" in str(exc)
        else:  # pragma: no cover - defensive
            raise AssertionError("expected GoogleAuthError")
        assert route.call_count == 0
    finally:
        conn.close()


def test_sync_410_triggers_full_resync(respx_mock, monkeypatch):
    """A 410 on an incremental (syncToken) request must fall back to a full
    time-window sync and persist the new nextSyncToken."""
    conn = _conn()
    try:
        events_repo.create(
            conn, title="Old event", start_at="2026-11-09T04:30:00+00:00",
            end_at="2026-11-09T05:30:00+00:00", tz="Asia/Kolkata",
            google_event_id="evt-old", etag="etag-0", turn_id="s",
        )
        settings_repo.set(conn, "google_sync_token", "tok-old", turn_id="s")

        monkeypatch.setattr(auth_module, "get_secret", lambda key: "refresh-123")
        monkeypatch.setattr(auth_module, "set_secret", lambda key, value: None)
        monkeypatch.setattr(auth_module, "delete_secret", lambda key: None)
        respx_mock.post(auth_module.TOKEN_ENDPOINT).mock(
            return_value=httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        )

        full_page = {
            "kind": "calendar#events",
            "items": [
                {"id": "evt-old", "status": "deleted"},
                {
                    "id": "evt-new", "status": "confirmed", "etag": "etag-new",
                    "summary": "Resynced event",
                    "start": {"dateTime": "2026-11-10T04:30:00Z", "timeZone": "Asia/Kolkata"},
                    "end": {"dateTime": "2026-11-10T05:30:00Z", "timeZone": "Asia/Kolkata"},
                },
            ],
            "nextPageToken": None,
            "nextSyncToken": "tok-new",
        }
        seen_params = []

        def calendar_handler(request):
            seen_params.append(request.url.params.get("syncToken"))
            if seen_params[-1] is not None:  # incremental request with a token -> 410
                return httpx.Response(410)
            return httpx.Response(200, json=full_page)

        route = respx_mock.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        ).mock(side_effect=calendar_handler)

        auth = GoogleAuth("cid", "secret")
        result = sync_calendar(conn, CalendarClient(auth), "primary")
        assert result == {"synced": 1, "deleted": 1}

        # First call used the (now-stale) sync token -> 410; second used none -> full.
        assert seen_params == ["tok-old", None]
        assert route.call_count == 2

        rows = events_repo.list_window(conn, start_at="2026-01-01T00:00:00+00:00", end_at="2027-01-01T00:00:00+00:00")
        titles = {r["title"] for r in rows if r["deleted_at"] is None}
        assert titles == {"Resynced event"}
        new_event = next(r for r in rows if r["google_event_id"] == "evt-new")
        assert new_event["etag"] == "etag-new"
        raw_old = conn.execute(
            "SELECT deleted_at FROM events WHERE google_event_id=?", ("evt-old",)
        ).fetchone()
        assert raw_old is not None and raw_old[0] is not None  # deleted via full resync
        assert settings_repo.get(conn, "google_sync_token") == "tok-new"
    finally:
        conn.close()


def test_sync_410_persists_after_retry(respx_mock, monkeypatch):
    """Two consecutive 410s must propagate as an error (no infinite retry)."""
    conn = _conn()
    try:
        settings_repo.set(conn, "google_sync_token", "tok-old", turn_id="s")
        monkeypatch.setattr(auth_module, "get_secret", lambda key: "refresh-123")
        monkeypatch.setattr(auth_module, "set_secret", lambda key, value: None)
        monkeypatch.setattr(auth_module, "delete_secret", lambda key: None)
        respx_mock.post(auth_module.TOKEN_ENDPOINT).mock(
            return_value=httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        )
        respx_mock.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        ).mock(return_value=httpx.Response(410))

        auth = GoogleAuth("cid", "secret")
        try:
            sync_calendar(conn, CalendarClient(auth), "primary")
        except GoogleCalendarSyncTokenInvalid:
            pass
        else:  # pragma: no cover - defensive
            raise AssertionError("expected GoogleCalendarSyncTokenInvalid")
    finally:
        conn.close()


def test_sync_skips_unchanged_etag(respx_mock, monkeypatch):
    """Re-syncing an event whose etag is unchanged must skip the write."""
    conn = _conn()
    try:
        monkeypatch.setattr(auth_module, "get_secret", lambda key: "refresh-123")
        monkeypatch.setattr(auth_module, "set_secret", lambda key, value: None)
        monkeypatch.setattr(auth_module, "delete_secret", lambda key: None)
        respx_mock.post(auth_module.TOKEN_ENDPOINT).mock(
            return_value=httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        )
        page = {
            "kind": "calendar#events",
            "items": [
                {
                    "id": "evt-1", "status": "confirmed", "etag": "etag-1",
                    "summary": "Unchanged event",
                    "start": {"dateTime": "2026-11-10T04:30:00Z", "timeZone": "Asia/Kolkata"},
                    "end": {"dateTime": "2026-11-10T05:30:00Z", "timeZone": "Asia/Kolkata"},
                },
            ],
            "nextPageToken": None,
            "nextSyncToken": "tok-1",
        }
        respx_mock.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        ).mock(return_value=httpx.Response(200, json=page))

        auth = GoogleAuth("cid", "secret")
        client = CalendarClient(auth)
        r1 = sync_calendar(conn, client, "primary")
        assert r1 == {"synced": 1, "deleted": 0}

        # Same payload again: etag unchanged, so nothing is written.
        r2 = sync_calendar(conn, client, "primary")
        assert r2 == {"synced": 0, "deleted": 0}

        rows = events_repo.list_window(conn, start_at="2026-01-01T00:00:00+00:00", end_at="2027-01-01T00:00:00+00:00")
        assert [r["title"] for r in rows] == ["Unchanged event"]
    finally:
        conn.close()


def test_sync_failure_recorded(respx_mock, monkeypatch):
    """A sync failure is recorded in settings so the UI can show a chip."""
    conn = _conn()
    try:
        settings_repo.set(conn, "google_sync_token", "tok-old", turn_id="s")
        monkeypatch.setattr(auth_module, "get_secret", lambda key: "refresh-123")
        monkeypatch.setattr(auth_module, "set_secret", lambda key, value: None)
        monkeypatch.setattr(auth_module, "delete_secret", lambda key: None)
        respx_mock.post(auth_module.TOKEN_ENDPOINT).mock(
            return_value=httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        )
        respx_mock.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        ).mock(return_value=httpx.Response(500, json={"error": {"message": "boom"}}))

        auth = GoogleAuth("cid", "secret")
        try:
            sync_calendar(conn, CalendarClient(auth), "primary")
        except GoogleCalendarError:
            pass
        else:  # pragma: no cover - defensive
            raise AssertionError("expected GoogleCalendarError")

        assert settings_repo.get(conn, "google_sync_failed") == "1"
        assert "500" in settings_repo.get(conn, "google_sync_error")
    finally:
        conn.close()


def _oauth_and_time_window(respx_mock, monkeypatch):
    monkeypatch.setattr(auth_module, "get_secret", lambda key: "refresh-123")
    monkeypatch.setattr(auth_module, "set_secret", lambda key, value: None)
    monkeypatch.setattr(auth_module, "delete_secret", lambda key: None)
    respx_mock.post(auth_module.TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
    )


def test_list_events_403_insufficient_permissions(respx_mock, monkeypatch):
    _oauth_and_time_window(respx_mock, monkeypatch)
    respx_mock.get(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    ).mock(
        return_value=httpx.Response(
            403,
            json={
                "error": {
                    "code": 403,
                    "message": "Insufficient Permission",
                    "errors": [{"reason": "insufficientPermissions", "message": "Insufficient Permission"}],
                }
            },
        )
    )
    auth = GoogleAuth("cid", "secret")
    client = CalendarClient(auth)
    with pytest.raises(GoogleCalendarError) as exc:
        client.list_events(
            "primary",
            time_min="2026-11-11T00:00:00Z",
            time_max="2026-11-18T00:00:00Z",
        )
    assert exc.value.status_code == 403
    assert "insufficientPermissions" in exc.value.reason
    assert "calendar.events" in exc.value.user_message()
    assert "Re-connect Google" in exc.value.user_message()


def test_list_events_403_access_not_configured(respx_mock, monkeypatch):
    _oauth_and_time_window(respx_mock, monkeypatch)
    respx_mock.get(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    ).mock(
        return_value=httpx.Response(
            403,
            json={
                "error": {
                    "code": 403,
                    "message": "Access Not Configured",
                    "errors": [{"reason": "accessNotConfigured", "message": "Access Not Configured"}],
                }
            },
        )
    )
    auth = GoogleAuth("cid", "secret")
    client = CalendarClient(auth)
    with pytest.raises(GoogleCalendarError) as exc:
        client.list_events(
            "primary",
            time_min="2026-11-11T00:00:00Z",
            time_max="2026-11-18T00:00:00Z",
        )
    assert exc.value.status_code == 403
    assert "accessNotConfigured" in exc.value.reason
    assert "Google Cloud Console" in exc.value.user_message()


def test_sync_calendar_records_distinct_403_user_messages(respx_mock, monkeypatch):
    for reason, needle in (("insufficientPermissions", "Re-connect Google"), ("accessNotConfigured", "Google Cloud Console")):
        conn = _conn()
        try:
            _oauth_and_time_window(respx_mock, monkeypatch)
            respx_mock.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events"
            ).mock(
                return_value=httpx.Response(
                    403,
                    json={
                        "error": {
                            "code": 403,
                            "message": "boom",
                            "errors": [{"reason": reason, "message": "boom"}],
                        }
                    },
                )
            )
            auth = GoogleAuth("cid", "secret")
            client = CalendarClient(auth)
            try:
                sync_calendar(conn, client, "primary")
            except GoogleCalendarError:
                pass
            else:  # pragma: no cover - defensive
                raise AssertionError(f"expected GoogleCalendarError for {reason}")
            assert settings_repo.get(conn, "google_sync_failed") == "1"
            error = settings_repo.get(conn, "google_sync_error")
            assert needle in error, error
        finally:
            conn.close()
