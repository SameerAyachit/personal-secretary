"""Memory facts tools (plan §8.5)."""

from __future__ import annotations

from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import facts as facts_repo
from secretary.tools import memory as memory_tools


def _conn(tmp_path) -> Connection:
    db = tmp_path / "mem.db"
    conn = Connection(db)
    migrate(conn._con, migrations_folder(), lambda: None)
    return conn


def test_memory_remember_upserts_fact(tmp_path):
    conn = _conn(tmp_path)
    result = memory_tools.memory_remember(conn, "turn-1", {"key": "name", "value": "Sameer"})
    assert result["key"] == "name"
    assert result["value"] == "Sameer"
    assert facts_repo.get(conn, "name") == "Sameer"


def test_memory_remember_updates_existing(tmp_path):
    conn = _conn(tmp_path)
    facts_repo.upsert(conn, "name", "Old")
    result = memory_tools.memory_remember(conn, "turn-1", {"key": "name", "value": "New"})
    assert result["value"] == "New"
    assert facts_repo.get(conn, "name") == "New"


def test_memory_forget_removes_fact(tmp_path):
    conn = _conn(tmp_path)
    facts_repo.upsert(conn, "name", "Sameer")
    result = memory_tools.memory_forget(conn, "turn-1", {"key": "name"})
    assert result["forgot"] is True
    assert facts_repo.get(conn, "name") is None


def test_memory_forget_missing(tmp_path):
    conn = _conn(tmp_path)
    result = memory_tools.memory_forget(conn, "turn-1", {"key": "missing"})
    assert result["forgot"] is False
