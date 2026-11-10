"""Guard: tests must never touch real Windows Credential Manager or the real
project-root credentials.json.

Fails if keyring is backed by the real Windows backend or if
SECRETARY_CREDENTIALS / SECRETARY_DATA_ROOT point at real paths. Passes when
the session fixture (conftest._guard_keyring_and_paths) routes keyring to an
in-memory backend and the paths to temp locations.

Safe to run against the real backend: it only inspects backend type and env
vars, it never writes or reads a secret.
"""

from __future__ import annotations

import os
from pathlib import Path

import keyring
from conftest import _InMemoryKeyring


def test_keyring_is_in_memory_backend():
    backend = keyring.get_keyring()
    assert isinstance(backend, _InMemoryKeyring), (
        f"keyring backend is {backend!r}, expected in-memory backend "
        "(real Windows Credential Manager must not be used in tests)"
    )


def test_credentials_path_is_temp():
    creds = os.environ.get("SECRETARY_CREDENTIALS", "")
    assert creds, "SECRETARY_CREDENTIALS must be set to a temp path"
    creds_path = Path(creds)
    assert creds_path.is_absolute()
    real_creds = Path("credentials.json").resolve()
    assert creds_path.resolve() != real_creds, (
        f"SECRETARY_CREDENTIALS={creds} must not be the real project-root "
        "credentials.json"
    )


def test_data_root_is_temp():
    root = os.environ.get("SECRETARY_DATA_ROOT", "")
    assert root, "SECRETARY_DATA_ROOT must be set to a temp path"
    assert Path(root).is_absolute()
    assert Path(root).resolve() != Path.home().resolve(), (
        f"SECRETARY_DATA_ROOT={root} must not be the real user profile"
    )
