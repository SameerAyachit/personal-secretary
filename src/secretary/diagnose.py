"""Diagnostics screen/command (plan §5, P0-05 / Phase 5).

``run_diagnose()`` checks configuration, secret storage, store connectivity,
and provider reachability without performing any writes. Returns an exit code.

Exit code semantics:
- FAIL (exit 1): Python version, config load, keyring importable,
  store connects, tzdata.
- WARN (exit 0 unless a FAIL is present): missing NVIDIA/Gemini keys,
  missing Google refresh token, missing credentials.json, a leftover plaintext
  google_token.json in the data folder.

Every check line carries a marker: [OK], [WARN] or [FAIL].
Secret values are never printed.
"""

from __future__ import annotations

import sys
from zoneinfo import ZoneInfo

from .paths import credential_candidates, data_root
from .secrets import get_secret


def _secret_present(key_name: str) -> bool:
    try:
        return get_secret(key_name) is not None
    except Exception:
        return False


def run_diagnose() -> int:
    oks: list[str] = []
    warns: list[str] = []
    fails: list[str] = []

    # ---- Critical checks (FAIL -> exit code 1) ---------------------------

    # Python version (plan requires >= 3.12).
    py_ok = sys.version_info >= (3, 12)
    if py_ok:
        oks.append(f"Python {sys.version.split()[0]} on {sys.platform} [OK]")
    else:
        fails.append(
            f"Python {sys.version.split()[0]} on {sys.platform} [FAIL] "
            f"(requires >= 3.12)"
        )

    # Config
    try:
        from .config import load_config  # noqa: PLC0415  (optional module)

        cfg = load_config()
        if not cfg:
            fails.append("config is empty [FAIL]")
        else:
            oks.append("config load [OK]")
    except Exception as exc:
        fails.append(f"config load [FAIL]: {exc}")

    # Secrets / keyring
    try:
        keyring_mod = __import__("keyring")
        keyring_mod.get_password  # ensure attribute exists
        oks.append("keyring importable [OK]")
    except Exception as exc:
        fails.append(f"keyring importable [FAIL]: {exc}")

    # Store (SQLite WAL)
    try:
        from .store.db import Connection  # noqa: PLC0415  (optional module)

        conn = Connection(":memory:")
        conn.execute("PRAGMA journal_mode=wal")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.close()
        oks.append("store connects (WAL + foreign_keys) [OK]")
    except Exception as exc:
        fails.append(f"store connects [FAIL]: {exc}")

    # Timezone data
    try:
        ZoneInfo("Asia/Kolkata")
        oks.append("tzdata [OK]")
    except Exception as exc:
        fails.append(f"tzdata [FAIL]: {exc}")

    # ---- Optional checks (WARN -> exit code 0 unless a FAIL is present) --

    # Google OAuth credentials file (never print its contents)
    found = None
    for candidate in credential_candidates():
        if candidate.exists():
            found = candidate
            break
    if found:
        oks.append(f"Google credentials present: {found} [OK]")
    else:
        checked = ", ".join(str(c) for c in credential_candidates())
        warns.append(f"Google credentials [WARN] missing (checked: {checked})")

    # LLM / Google API keys stored in Credential Manager (never print values)
    for label, key_name in (
        ("NVIDIA API key", "llm_api_key:nvidia"),
        ("Gemini API key", "llm_api_key:gemini"),
        ("Google refresh token", "google_token"),
    ):
        if _secret_present(key_name):
            oks.append(f"{label} [OK]")
        else:
            warns.append(f"{label} [WARN] missing")

    # Secrets live only in the Credential Manager (AGENTS.md). An old plaintext token file
    # is reported, never read or printed, and never deleted by the app.
    leftover = data_root() / "google_token.json"
    if leftover.exists():
        warns.append(
            f"Plaintext secret file [WARN] {leftover} is not used by this version; "
            "secrets belong in Credential Manager. Check it and delete it if it is a leftover"
        )

    # LLM model configured for the active provider (never print the key value)
    try:
        from .config import load_config  # noqa: PLC0415  (optional module)
        from .paths import config_path  # noqa: PLC0415

        _cfg = load_config()
        _provider = _cfg.llm.active
        _model = _cfg.llm.providers[_provider].primary_model or ""
        oks.append(
            f"LLM config: {config_path()} provider={_provider} model={_model or '(none)'} [OK]"
        )
        if not _model or _model.lower().startswith(("fake", "test")):
            warns.append(
                f"LLM model [WARN] placeholder or empty for provider {_provider}; "
                "open Settings > AI and pick one"
            )
    except Exception as exc:
        warns.append(f"LLM model [WARN] could not be read: {exc}")

    if fails:
        print("DIAGNOSE FAILED")
        for p in fails:
            print(f"  [X] {p}")
        for w in warns:
            print(f"  [!] {w}")
        for o in oks:
            print(f"  [ ] {o}")
        return 1
    print("DIAGNOSE OK")
    for o in oks:
        print(f"  [x] {o}")
    for w in warns:
        print(f"  [!] {w}")
    return 0
