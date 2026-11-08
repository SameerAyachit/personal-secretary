"""Migration runner tests (plan §5.2)."""

import sqlite3
from pathlib import Path

import pytest

from secretary.store.db import migrations_folder
from secretary.store.migrate import migrate


def _connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def test_apply_all_migrations_to_empty_db(tmp_path):
    db = tmp_path / "secretary.db"
    con = _connect(db)
    try:
        backup_called = []
        def backup_cb():
            backup_called.append(True)
        migrate(con, migrations_folder(), backup_cb)
        applied = {r[0] for r in con.execute("SELECT version FROM schema_migrations")}
        files = sorted(migrations_folder().glob("[0-9][0-9][0-9]_*.sql"))
        expected = {int(f.name[:3]) for f in files}
        assert applied == expected
        assert backup_called == []  # no backup needed on empty DB
        # user_version set to latest
        assert con.execute("PRAGMA user_version").fetchone()[0] == max(expected)
        # core tables exist
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"tasks", "reminders", "inbox", "pending_actions", "action_log", "schema_migrations"} <= names
    finally:
        con.close()


def test_migration_runner_is_idempotent(tmp_path):
    db = tmp_path / "secretary.db"
    con = _connect(db)
    try:
        migrate(con, migrations_folder(), lambda: None)
        migrate(con, migrations_folder(), lambda: None)  # second run: no-op
        applied = [r[0] for r in con.execute("SELECT version FROM schema_migrations ORDER BY version")]
        assert applied == sorted(applied)
        assert len(applied) == len(set(applied))
    finally:
        con.close()


def test_refuses_newer_database(tmp_path, monkeypatch):
    db = tmp_path / "secretary.db"
    con = _connect(db)
    try:
        # Simulate a DB that has a migration newer than the code.
        con.execute("""CREATE TABLE IF NOT EXISTS schema_migrations(
            version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)""")
        con.execute("BEGIN IMMEDIATE")
        con.execute("INSERT INTO schema_migrations VALUES (999, 'fake_future.sql', '2020-01-01T00:00:00Z')")
        con.execute("PRAGMA user_version = 999")
        con.execute("COMMIT")
        with pytest.raises(RuntimeError, match="newer than this app"):
            migrate(con, migrations_folder(), lambda: None)
    finally:
        con.close()
