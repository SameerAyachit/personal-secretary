"""Secret storage via keyring (Windows Credential Manager) (plan §6, D9).

Service name ``Secretary``; key names like ``llm_api_key:groq`` and
``google_token``. Credential Manager blobs are limited (~2.5 KB), so store the
refresh token only and rebuild access tokens in memory (§6.3). Never log or
return the raw value outside this module.
"""

from __future__ import annotations

import contextlib

import keyring

_SERVICE = "Secretary"


def set_secret(key_name: str, value: str) -> None:
    keyring.set_password(_SERVICE, key_name, value)


def get_secret(key_name: str) -> str | None:
    return keyring.get_password(_SERVICE, key_name)


def delete_secret(key_name: str) -> None:
    with contextlib.suppress(keyring.errors.PasswordDeleteError):
        keyring.delete_password(_SERVICE, key_name)
