"""Tests for secrets.py — round-trip through a faked keyring (no real Credential Manager)."""

import secretary.secrets as s


class _FakeKeyring:
    def __init__(self) -> None:
        self.store: dict[str, str | None] = {}

    def set_password(self, service, key_name, value) -> None:
        self.store[key_name] = value

    def get_password(self, service, key_name):
        return self.store.get(key_name)

    def delete_password(self, service, key_name) -> None:
        self.store.pop(key_name, None)


def test_secrets_round_trip(monkeypatch):
    fake = _FakeKeyring()
    monkeypatch.setattr(s.keyring, "set_password", fake.set_password)
    monkeypatch.setattr(s.keyring, "get_password", fake.get_password)
    monkeypatch.setattr(s.keyring, "delete_password", fake.delete_password)

    s.set_secret("llm_api_key:groq", "sk-abc123")
    assert s.get_secret("llm_api_key:groq") == "sk-abc123"
    assert s.get_secret("missing") is None

    s.delete_secret("llm_api_key:groq")
    assert s.get_secret("llm_api_key:groq") is None

    # Deleting a missing key must not raise.
    s.delete_secret("does-not-exist")
