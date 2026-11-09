"""Google Calendar sync: Calendar API mocked with respx (no real credentials)."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import httpx

import secretary.integrations.google.auth as auth_module
from secretary.integrations.google.auth import GoogleAuth, GoogleAuthError
from secretary.integrations.google.calendar import CalendarClient, sync_calendar
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
