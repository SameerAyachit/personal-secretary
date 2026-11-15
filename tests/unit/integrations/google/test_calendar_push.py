"""Calendar write-back: local events created in chat are pushed to Google."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import httpx

import secretary.integrations.google.auth as auth_module
from secretary.integrations.google.auth import GoogleAuth
from secretary.integrations.google.calendar import CalendarClient, push_pending_events
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import events as events_repo

EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "p.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


def _client(respx_mock, monkeypatch) -> CalendarClient:
    monkeypatch.setattr(auth_module, "get_secret", lambda key: "refresh-123")
    respx_mock.post(auth_module.TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"access_token": "at", "expires_in": 3600})
    )
    return CalendarClient(GoogleAuth("cid", "secret"))


def _pending(conn, **over) -> int:
    fields = dict(
        title="Dentist", start_at="2026-11-15T11:30:00+00:00",
        end_at="2026-11-15T12:30:00+00:00", tz="Asia/Kolkata", all_day=0,
        location="Clinic", google_event_id="a" * 32, sync_state="pending",
    )
    fields.update(over)
    return events_repo.create(conn, **fields)


def test_pending_event_is_posted_and_marked_synced(respx_mock, monkeypatch):
    client = _client(respx_mock, monkeypatch)
    route = respx_mock.post(EVENTS_URL).mock(
        return_value=httpx.Response(200, json={"id": "a" * 32, "etag": '"e1"'})
    )
    conn = _conn()
    eid = _pending(conn)
    assert push_pending_events(conn, client) == 1
    body = json.loads(route.calls[0].request.content)
    assert body["id"] == "a" * 32 and body["summary"] == "Dentist"
    assert body["start"] == {"dateTime": "2026-11-15T11:30:00+00:00", "timeZone": "Asia/Kolkata"}
    assert body["location"] == "Clinic"
    row = conn.execute("SELECT sync_state, etag FROM events WHERE id=?", (eid,)).fetchone()
    assert (row[0], row[1]) == ("synced", '"e1"')
    assert push_pending_events(conn, client) == 0  # nothing left to push


def test_all_day_event_uses_date_fields(respx_mock, monkeypatch):
    client = _client(respx_mock, monkeypatch)
    route = respx_mock.post(EVENTS_URL).mock(return_value=httpx.Response(200, json={"id": "x"}))
    conn = _conn()
    _pending(conn, all_day=1, start_at="2026-11-14T18:30:00+00:00", end_at="2026-11-15T18:30:00+00:00")
    push_pending_events(conn, client)
    body = json.loads(route.calls[0].request.content)
    assert body["start"] == {"date": "2026-11-15"} and body["end"] == {"date": "2026-11-16"}


def test_conflict_409_counts_as_already_created(respx_mock, monkeypatch):
    client = _client(respx_mock, monkeypatch)
    respx_mock.post(EVENTS_URL).mock(
        return_value=httpx.Response(409, json={"error": {"message": "identifier already exists"}})
    )
    conn = _conn()
    eid = _pending(conn)
    assert push_pending_events(conn, client) == 1
    assert conn.execute("SELECT sync_state FROM events WHERE id=?", (eid,)).fetchone()[0] == "synced"


def test_transient_failure_stays_pending_and_permanent_fails(respx_mock, monkeypatch):
    client = _client(respx_mock, monkeypatch)
    route = respx_mock.post(EVENTS_URL).mock(return_value=httpx.Response(503, json={}))
    conn = _conn()
    eid = _pending(conn)
    assert push_pending_events(conn, client) == 0
    assert conn.execute("SELECT sync_state FROM events WHERE id=?", (eid,)).fetchone()[0] == "pending"
    route.mock(return_value=httpx.Response(400, json={"error": {"message": "bad"}}))
    push_pending_events(conn, client)
    row = conn.execute("SELECT sync_state, sync_error FROM events WHERE id=?", (eid,)).fetchone()
    assert row[0] == "failed" and "400" in row[1]


def test_event_already_on_google_is_patched_not_reinserted(respx_mock, monkeypatch):
    client = _client(respx_mock, monkeypatch)
    patch_route = respx_mock.patch(f"{EVENTS_URL}/{'a' * 32}").mock(
        return_value=httpx.Response(200, json={"id": "a" * 32, "etag": '"e2"'})
    )
    post_route = respx_mock.post(EVENTS_URL).mock(return_value=httpx.Response(200, json={}))
    conn = _conn()
    eid = _pending(conn, title="Dentist (moved)", etag='"e1"')  # etag set: Google already has it
    assert push_pending_events(conn, client) == 1
    assert not post_route.called
    body = json.loads(patch_route.calls[0].request.content)
    assert body["summary"] == "Dentist (moved)"
    row = conn.execute("SELECT sync_state, etag FROM events WHERE id=?", (eid,)).fetchone()
    assert (row[0], row[1]) == ("synced", '"e2"')


def test_patch_404_marks_the_event_failed(respx_mock, monkeypatch):
    client = _client(respx_mock, monkeypatch)
    respx_mock.patch(f"{EVENTS_URL}/{'a' * 32}").mock(return_value=httpx.Response(404, json={}))
    conn = _conn()
    eid = _pending(conn, etag='"e1"')
    assert push_pending_events(conn, client) == 0
    assert conn.execute("SELECT sync_state FROM events WHERE id=?", (eid,)).fetchone()[0] == "failed"
