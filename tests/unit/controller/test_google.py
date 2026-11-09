"""Controller Google connect/reconnect (oauth flow + Credential Manager)."""
from __future__ import annotations

import secretary.controller as cm
from secretary.controller import Controller
from secretary.integrations.google.oauth import (
    CLIENT_ID_KEY,
    REFRESH_TOKEN_KEY,
    GoogleOAuthError,
)
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate


def _conn(tmp_path):
    tmp = tmp_path / "g.db"
    conn = Connection(tmp)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn, migrations_folder(), lambda: None)
    return conn


class _FakeFlow:
    def __init__(self, store, token="rt-xyz", raise_exc=None):
        self._store = store
        self._token = token
        self._raise_exc = raise_exc

    def run(self):
        if self._raise_exc:
            raise self._raise_exc
        self._store[REFRESH_TOKEN_KEY] = self._token


def test_get_google_connected_false_when_no_token(monkeypatch, tmp_path):
    monkeypatch.setattr(cm, "connected", lambda: False)
    controller = Controller(_conn(tmp_path))
    assert controller.get_google_connected() is False


def test_get_google_connected_true_when_token(monkeypatch, tmp_path):
    monkeypatch.setattr(cm, "connected", lambda: True)
    controller = Controller(_conn(tmp_path))
    assert controller.get_google_connected() is True


def test_connect_google_stores_token(monkeypatch, tmp_path):
    store = {}
    monkeypatch.setattr(cm, "connected", lambda: store.get(REFRESH_TOKEN_KEY) is not None)
    monkeypatch.setattr(cm, "disconnect", lambda: store.pop(REFRESH_TOKEN_KEY, None))
    monkeypatch.setattr(cm, "credentials_path", lambda: tmp_path / "credentials.json")
    (tmp_path / "credentials.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        cm,
        "GoogleOAuthFlow",
        type("F", (), {"from_credentials_file": lambda path: _FakeFlow(store)}),
    )

    controller = Controller(_conn(tmp_path))
    controller._connect_google_background()
    assert store.get(REFRESH_TOKEN_KEY) == "rt-xyz"


def test_connect_google_invalid_grant_disconnects(monkeypatch, tmp_path):
    store = {}
    disconnected = []
    monkeypatch.setattr(cm, "connected", lambda: store.get(REFRESH_TOKEN_KEY) is not None)
    monkeypatch.setattr(
        cm,
        "disconnect",
        lambda: disconnected.append(REFRESH_TOKEN_KEY)
        or store.pop(REFRESH_TOKEN_KEY, None),
    )
    monkeypatch.setattr(cm, "credentials_path", lambda: tmp_path / "credentials.json")
    (tmp_path / "credentials.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cm, "is_invalid_grant", lambda exc: True)
    monkeypatch.setattr(
        cm,
        "GoogleOAuthFlow",
        type(
            "F",
            (),
            {
                "from_credentials_file": lambda path: _FakeFlow(
                    store, raise_exc=GoogleOAuthError("invalid_grant")
                )
            },
        ),
    )

    controller = Controller(_conn(tmp_path))
    controller._connect_google_background()
    assert store.get(REFRESH_TOKEN_KEY) is None
    assert REFRESH_TOKEN_KEY in disconnected


def test_connect_google_missing_credentials(monkeypatch, tmp_path):
    store = {}
    monkeypatch.setattr(cm, "connected", lambda: False)
    monkeypatch.setattr(cm, "disconnect", lambda: None)
    monkeypatch.setattr(cm, "credentials_path", lambda: tmp_path / "credentials.json")
    # No credentials.json file -> flow factory raises FileNotFoundError.
    monkeypatch.setattr(
        cm,
        "GoogleOAuthFlow",
        type("F", (), {"from_credentials_file": lambda path: (_ for _ in ()).throw(FileNotFoundError())}),
    )

    controller = Controller(_conn(tmp_path))
    controller._connect_google_background()
    assert store.get(REFRESH_TOKEN_KEY) is None


def test_disconnect_google(monkeypatch, tmp_path):
    store = {REFRESH_TOKEN_KEY: "rt-xyz", CLIENT_ID_KEY: "cid"}
    monkeypatch.setattr(cm, "connected", lambda: store.get(REFRESH_TOKEN_KEY) is not None)
    monkeypatch.setattr(
        cm,
        "disconnect",
        lambda: (store.pop(REFRESH_TOKEN_KEY, None), store.pop(CLIENT_ID_KEY, None)),
    )

    controller = Controller(_conn(tmp_path))
    controller.disconnect_google()
    assert REFRESH_TOKEN_KEY not in store
    assert CLIENT_ID_KEY not in store
