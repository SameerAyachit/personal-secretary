"""Schema migration runner (plan §5.2).

Forward-only migrations tracked in a ``schema_migrations`` table. The app
refuses to start if the database is newer than the code.
"""

from __future__ import annotations

import pathlib
import sqlite3
import time


def split_statements(sql: str):
    buf = ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            yield buf.strip()
            buf = ""
    if buf.strip():
        yield buf.strip()


def migrate(con: sqlite3.Connection, folder: pathlib.Path, backup_cb) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations(
        version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"""
    )
    applied = {r[0] for r in con.execute("SELECT version FROM schema_migrations")}
    files = sorted(folder.glob("[0-9][0-9][0-9]_*.sql"))
    versions = [int(f.name[:3]) for f in files]
    assert versions == sorted(set(versions)), "duplicate or unordered migration numbers"
    pending = [f for f in files if int(f.name[:3]) not in applied]
    if applied and max(applied) > max(versions):
        raise RuntimeError("Database is newer than this app. Refusing to start.")
    if pending and applied:
        backup_cb()  # backup BEFORE touching the schema
    for f in pending:
        con.execute("BEGIN IMMEDIATE")
        try:
            for stmt in split_statements(f.read_text(encoding="utf-8")):
                con.execute(stmt)
            con.execute(
                "INSERT INTO schema_migrations VALUES (?,?,?)",
                (int(f.name[:3]), f.name, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
            )
            con.execute(f"PRAGMA user_version = {int(f.name[:3])}")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
