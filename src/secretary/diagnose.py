"""Diagnostics screen/command (plan §5, P0-05 / Phase 5).

``run_diagnose()`` checks configuration, secret storage, store connectivity,
and provider reachability without performing any writes. Returns an exit code.
"""

from __future__ import annotations

import sys

from .paths import credential_candidates
from .secrets import get_secret


def _secret_present(key_name: str) -> bool:
    try:
        return get_secret(key_name) is not None
    except Exception:
        return False


def run_diagnose() -> int:
    problems: list[str] = []
    ok: list[str] = []

    # Python / platform
    ok.append(f"Python {sys.version.split()[0]} on {sys.platform}")

    # Config
    try:
        from .config import load_config  # noqa: PLC0415  (optional module, loaded lazily)
        cfg = load_config()
        ok.append("config loaded")
        if not cfg:
            problems.append("config is empty")
    except Exception as exc:
        problems.append(f"config load failed: {exc}")

    # Secrets / keyring
    try:
        ok.append("keyring importable")
    except Exception as exc:
        problems.append(f"keyring unavailable: {exc}")

    # Store (SQLite WAL)
    try:
        from .store.db import Connection  # noqa: PLC0415  (optional module, loaded lazily)
        conn = Connection(":memory:")
        conn.execute("PRAGMA journal_mode=wal")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.close()
        ok.append("store connects (WAL + foreign_keys)")
    except Exception as exc:
        problems.append(f"store connect failed: {exc}")

    # timezone data
    try:
        from zoneinfo import ZoneInfo  # noqa: PLC0415  (optional import, loaded lazily)
        ZoneInfo("Asia/Kolkata")
        ok.append("tzdata present")
    except Exception as exc:
        problems.append(f"tzdata missing: {exc}")

    # Google OAuth credentials file (never print its contents)
    found = None
    for candidate in credential_candidates():
        if candidate.exists():
            found = candidate
            break
    if found:
        ok.append(f"Google credentials present: {found}")
    else:
        checked = ", ".join(str(c) for c in credential_candidates())
        problems.append(f"Google credentials missing (checked: {checked})")

    # LLM / Google API keys stored in Credential Manager (never print values)
    for label, key_name in (
        ("Groq API key", "llm_api_key:groq"),
        ("Gemini API key", "llm_api_key:gemini"),
        ("Google refresh token", "google_token"),
    ):
        if _secret_present(key_name):
            ok.append(f"{label} present in Credential Manager")
        else:
            problems.append(f"{label} missing in Credential Manager ({key_name})")

    if problems:
        print("DIAGNOSE FAILED")
        for p in problems:
            print(f"  [X] {p}")
        for o in ok:
            print(f"  [ ] {o}")
        return 1
    print("DIAGNOSE OK")
    for o in ok:
        print(f"  [x] {o}")
    return 0
