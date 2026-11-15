"""Daily update check (plan 18.3).

One unauthenticated ``GET https://api.github.com/repos/<repo>/releases/latest`` per day.
Nothing about the user or the install is sent: no token, no cookies, and a generic
User-Agent without a version. The answer is reduced to a tag and a github.com link and
stored in the ``settings`` table; the UI shows an "Update available" banner. Nothing is
downloaded or installed automatically (v1 updates are manual).
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from secretary.store.repos import settings as settings_repo

logger = logging.getLogger(__name__)

RELEASES_HOST = "api.github.com"
_LINK_PREFIX = "https://github.com/"
_TURN = "update-check"
_USER_AGENT = "secretary-update-check"

_SUCCESS_INTERVAL = timedelta(hours=24)
_FAILURE_INTERVAL = timedelta(hours=1)

_K_TAG = "update_latest_tag"
_K_URL = "update_latest_url"
_K_NEXT = "update_next_check"
_K_DISMISSED = "update_dismissed_tag"


class _Release(BaseModel):
    tag_name: str
    html_url: str
    draft: bool = False
    prerelease: bool = False


def parse_version(text: str) -> tuple[int, ...] | None:
    """``v1.2.3`` / ``1.2`` -> ``(1, 2, 3)`` / ``(1, 2)``; anything else -> ``None``."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (text or "").strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(latest: str, current: str) -> bool:
    new, old = parse_version(latest), parse_version(current)
    return new is not None and old is not None and new > old


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _due(conn: Any, now: datetime) -> bool:
    stored = settings_repo.get(conn, _K_NEXT)
    if not stored:
        return True
    try:
        return now >= datetime.fromisoformat(stored.replace("Z", "+00:00"))
    except ValueError:
        return True


def _fetch(repo: str, transport: httpx.BaseTransport | None) -> _Release | None:
    """The latest release, or ``None`` when there is none (404). Other failures raise."""
    url = f"https://{RELEASES_HOST}/repos/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": _USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(transport=transport, timeout=10.0, follow_redirects=False) as client:
        response = client.get(url, headers=headers)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return _Release.model_validate(response.json())


def available_update(conn: Any, current: str) -> dict[str, str] | None:
    """The stored newer release as ``{"tag", "url"}``, unless dismissed or not newer."""
    tag = settings_repo.get(conn, _K_TAG)
    url = settings_repo.get(conn, _K_URL)
    if not tag or not url or not is_newer(tag, current):
        return None
    if settings_repo.get(conn, _K_DISMISSED) == tag:
        return None
    return {"tag": tag, "url": url}


def dismiss(conn: Any, tag: str) -> None:
    """Hide the banner for this release; a newer release shows it again."""
    settings_repo.set(conn, _K_DISMISSED, tag, turn_id=_TURN)


def check_for_update(
    conn: Any,
    current: str,
    *,
    repo: str,
    now: datetime | None = None,
    enabled: bool = True,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, str] | None:
    """Run the daily check if it is due. Returns the update only when this call ran a check.

    Never raises: a network or parse problem is logged, remembered for an hour, and the
    previous answer stays in place.
    """
    if not enabled or not repo.strip():
        return None
    now = now or datetime.now(UTC)
    if not _due(conn, now):
        return None
    try:
        release = _fetch(repo.strip(), transport)
    except (httpx.HTTPError, ValidationError, ValueError) as exc:
        logger.info("update check failed: %s", type(exc).__name__)
        settings_repo.set(conn, _K_NEXT, _utc(now + _FAILURE_INTERVAL), turn_id=_TURN)
        return None
    settings_repo.set(conn, _K_NEXT, _utc(now + _SUCCESS_INTERVAL), turn_id=_TURN)
    if release is None or release.draft or release.prerelease:
        return None
    if not release.html_url.startswith(_LINK_PREFIX):
        logger.info("update check ignored a release link outside github.com")
        return None
    settings_repo.set(conn, _K_TAG, release.tag_name, turn_id=_TURN)
    settings_repo.set(conn, _K_URL, release.html_url, turn_id=_TURN)
    return available_update(conn, current)
