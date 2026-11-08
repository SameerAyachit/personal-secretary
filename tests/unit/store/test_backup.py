"""Backup / restore tests (plan §5.5)."""

import sqlite3
from pathlib import Path

from secretary.store.backup import backup, prune_backups, restore
from secretary.store.db import Connection


def _seed_db(path: Path) -> None:
    con = sqlite3.connect(str(path), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE tasks(id INTEGER PRIMARY KEY, title TEXT NOT NULL, created_at TEXT, updated_at TEXT)")
    con.execute("INSERT INTO tasks(title, created_at, updated_at) VALUES('seed', 't', 't')")
    con.close()


def test_backup_uses_online_api(tmp_path):
    src = tmp_path / "src.db"
    dst = tmp_path / "backups" / "secretary-20260101T000000Z.db"
    _seed_db(src)
    with Connection(src) as c:
        out = backup(c, dst)
    assert out == dst
    assert dst.exists()
    # The backup contains the seeded row.
    con = sqlite3.connect(str(dst))
    try:
        n = con.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        assert n == 1
    finally:
        con.close()


def test_prune_backups_keps_n(tmp_path):
    bdir = tmp_path / "backups"
    bdir.mkdir()
    for i in range(10):
        p = bdir / f"secretary-2026010{i}T000000Z.db"
        p.write_bytes(b"x")
    prune_backups(bdir, keep=3)
    remaining = sorted(p.name for p in bdir.glob("secretary-*.db"))
    assert len(remaining) == 3


def test_restore_replaces_db(tmp_path):
    src = tmp_path / "src.db"
    cur = tmp_path / "cur.db"
    _seed_db(src)
    # current DB has different content
    con = sqlite3.connect(str(cur), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE tasks(id INTEGER PRIMARY KEY, title TEXT NOT NULL, created_at TEXT, updated_at TEXT)")
    con.execute("INSERT INTO tasks(title, created_at, updated_at) VALUES('current', 't', 't')")
    con.close()

    safety = restore(src, cur)
    assert safety.exists()
    con = sqlite3.connect(str(cur))
    try:
        title = con.execute("SELECT title FROM tasks").fetchone()[0]
        assert title == "seed"
    finally:
        con.close()
