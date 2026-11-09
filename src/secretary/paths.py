"""Filesystem paths for the Secretary data root (plan §6.1).

Centralises every location so nothing is hardcoded. The data root defaults to
``%LOCALAPPDATA%\\Secretary`` on Windows; tests inject a temp root through the
``SECRETARY_DATA_ROOT`` environment variable (never touch the real profile in
tests, per EXECUTION_PROTOCOL §0).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _default_data_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Secretary"
    return Path.home() / ".secretary"


def data_root() -> Path:
    """The Secretary data root. Override with SECRETARY_DATA_ROOT (tests)."""
    env = os.environ.get("SECRETARY_DATA_ROOT")
    return Path(env) if env else _default_data_root()


def config_path() -> Path:
    return data_root() / "config.toml"


def credential_candidates() -> list[Path]:
    """Candidate credentials.json locations in priority order.

    1. ``SECRETARY_CREDENTIALS`` env var if set.
    2. ``%LOCALAPPDATA%\\Secretary\\credentials.json`` (installed app default).
    3. Project root ``credentials.json`` when running from source (not frozen).
    """
    env = os.environ.get("SECRETARY_CREDENTIALS")
    if env:
        return [Path(env)]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        installed = Path(local) / "Secretary" / "credentials.json"
        if not getattr(sys, "frozen", False):
            return [installed, Path(__file__).resolve().parents[2] / "credentials.json"]
        return [installed]
    if not getattr(sys, "frozen", False):
        return [Path(__file__).resolve().parents[2] / "credentials.json"]
    return [Path.home() / ".secretary" / "credentials.json"]


def credentials_path() -> Path:
    """Google OAuth client secret (BYO).

    Returns the first existing candidate in priority order, or the
    highest-priority default if none exists (so callers can display it).
    Never reads or logs the file contents.
    """
    for candidate in credential_candidates():
        if candidate.exists():
            return candidate
    return credential_candidates()[0]


def db_path() -> Path:
    return data_root() / "secretary.db"


def backups_dir() -> Path:
    return data_root() / "backups"


def logs_dir() -> Path:
    return data_root() / "logs"


def ensure_dirs() -> None:
    """Create the data root and standard subdirectories (idempotent)."""
    for p in (data_root(), backups_dir(), logs_dir()):
        p.mkdir(parents=True, exist_ok=True)
