"""Daily update check (plan 18.3): one unauthenticated GitHub call, fake transport only."""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from secretary.integrations import updates
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import settings as settings_repo

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
REPO = "owner/repo"


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "u.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


def _transport(payload=None, status=200, seen=None, error=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if error is not None:
            raise error
        return httpx.Response(status, json=payload if payload is not None else {})

    return httpx.MockTransport(handler)


def _release(tag="v0.2.0", **extra):
    return {"tag_name": tag, "html_url": f"https://github.com/{REPO}/releases/tag/{tag}", **extra}


def test_parse_version_and_comparison():
    assert updates.parse_version("v1.2.3") == (1, 2, 3)
    assert updates.parse_version("0.10") == (0, 10)
    assert updates.parse_version("nightly") is None
    assert updates.is_newer("v0.2.0", "0.1.0")
    assert updates.is_newer("v0.10.0", "0.9.0")  # numeric, not text, comparison
    assert not updates.is_newer("v0.1.0", "0.1.0")
    assert not updates.is_newer("v0.0.9", "0.1.0")
    assert not updates.is_newer("garbage", "0.1.0")


def test_request_is_anonymous_and_goes_to_the_releases_endpoint():
    conn = _conn()
    seen: list[httpx.Request] = []
    updates.check_for_update(conn, "0.1.0", repo=REPO, now=NOW, transport=_transport(_release(), seen=seen))
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "GET"
    assert str(request.url) == f"https://api.github.com/repos/{REPO}/releases/latest"
    assert "authorization" not in request.headers and "cookie" not in request.headers
    assert request.headers["user-agent"] == "secretary-update-check"  # generic: no version, name or email


def test_newer_release_is_recorded_and_reported():
    conn = _conn()
    info = updates.check_for_update(conn, "0.1.0", repo=REPO, now=NOW, transport=_transport(_release("v0.2.0")))
    assert info == {"tag": "v0.2.0", "url": f"https://github.com/{REPO}/releases/tag/v0.2.0"}
    assert updates.available_update(conn, "0.1.0") == info


def test_same_or_older_release_reports_nothing():
    conn = _conn()
    assert updates.check_for_update(conn, "0.2.0", repo=REPO, now=NOW, transport=_transport(_release("v0.2.0"))) is None
    assert updates.available_update(conn, "0.2.0") is None


def test_runs_at_most_once_a_day():
    conn = _conn()
    seen: list[httpx.Request] = []
    transport = _transport(_release(), seen=seen)
    updates.check_for_update(conn, "0.1.0", repo=REPO, now=NOW, transport=transport)
    updates.check_for_update(conn, "0.1.0", repo=REPO, now=NOW + timedelta(hours=3), transport=transport)
    assert len(seen) == 1
    updates.check_for_update(conn, "0.1.0", repo=REPO, now=NOW + timedelta(hours=24, minutes=1), transport=transport)
    assert len(seen) == 2


def test_failure_is_quiet_and_retried_within_the_hour_after():
    conn = _conn()
    seen: list[httpx.Request] = []
    boom = httpx.ConnectError("offline")
    assert updates.check_for_update(conn, "0.1.0", repo=REPO, now=NOW, transport=_transport(seen=seen, error=boom)) is None
    updates.check_for_update(conn, "0.1.0", repo=REPO, now=NOW + timedelta(minutes=30), transport=_transport(seen=seen, error=boom))
    assert len(seen) == 1  # not hammered
    updates.check_for_update(conn, "0.1.0", repo=REPO, now=NOW + timedelta(minutes=61), transport=_transport(_release(), seen=seen))
    assert len(seen) == 2


@pytest.mark.parametrize("status", [404, 403, 500])
def test_http_errors_report_nothing(status):
    conn = _conn()
    assert updates.check_for_update(conn, "0.1.0", repo=REPO, now=NOW, transport=_transport({"message": "x"}, status=status)) is None


@pytest.mark.parametrize("payload", [{}, {"tag_name": 5}, {"tag_name": "v9.9.9", "draft": True}, {"tag_name": "v9.9.9", "prerelease": True}])
def test_malformed_draft_or_prerelease_payloads_are_ignored(payload):
    conn = _conn()
    payload = dict(payload)
    payload.setdefault("html_url", "https://github.com/x/y/releases")
    assert updates.check_for_update(conn, "0.1.0", repo=REPO, now=NOW, transport=_transport(payload)) is None


def test_link_must_stay_on_github():
    conn = _conn()
    evil = {"tag_name": "v9.0.0", "html_url": "https://evil.example/download"}
    assert updates.check_for_update(conn, "0.1.0", repo=REPO, now=NOW, transport=_transport(evil)) is None


def test_disabled_makes_no_request():
    conn = _conn()
    seen: list[httpx.Request] = []
    out = updates.check_for_update(conn, "0.1.0", repo=REPO, now=NOW, enabled=False, transport=_transport(_release(), seen=seen))
    assert out is None and seen == []


def test_empty_repo_makes_no_request():
    conn = _conn()
    seen: list[httpx.Request] = []
    assert updates.check_for_update(conn, "0.1.0", repo="", now=NOW, transport=_transport(_release(), seen=seen)) is None
    assert seen == []


def test_dismissed_tag_hides_the_banner_until_a_newer_one():
    conn = _conn()
    updates.check_for_update(conn, "0.1.0", repo=REPO, now=NOW, transport=_transport(_release("v0.2.0")))
    assert updates.available_update(conn, "0.1.0") is not None
    updates.dismiss(conn, "v0.2.0")
    assert updates.available_update(conn, "0.1.0") is None
    updates.check_for_update(conn, "0.1.0", repo=REPO, now=NOW + timedelta(days=2), transport=_transport(_release("v0.3.0")))
    assert updates.available_update(conn, "0.1.0")["tag"] == "v0.3.0"


def test_nothing_personal_is_stored_beyond_tag_url_and_times():
    conn = _conn()
    updates.check_for_update(conn, "0.1.0", repo=REPO, now=NOW, transport=_transport(_release()))
    keys = {k for k in ("update_latest_tag", "update_latest_url", "update_next_check") if settings_repo.get(conn, k)}
    assert keys == {"update_latest_tag", "update_latest_url", "update_next_check"}
