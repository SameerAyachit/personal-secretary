"""Chat transcript repo: history order and conversation creation."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from secretary.store.db import migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import chat as chat_repo


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(str(Path(tempfile.mkdtemp()) / "c.db"), isolation_level=None)
    migrate(con, migrations_folder(), lambda: None)
    return con


def test_recent_messages_are_oldest_first_and_limited():
    con = _con()
    for i in range(5):
        chat_repo.add_message(con, "user" if i % 2 == 0 else "assistant", f"m{i}", f"t{i}")
    assert [m["content"] for m in chat_repo.recent_messages(con, 3)] == ["m2", "m3", "m4"]
    assert con.execute("SELECT count(*) FROM conversations").fetchone()[0] == 1


def test_non_chat_roles_are_excluded():
    con = _con()
    chat_repo.add_message(con, "user", "hi")
    chat_repo.add_message(con, "tool", "result")
    assert [m["role"] for m in chat_repo.recent_messages(con, 10)] == ["user"]
