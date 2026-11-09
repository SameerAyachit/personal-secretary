"""SQLite store connection (plan §5.4).

Pragmas on connect: journal_mode=WAL, synchronous=NORMAL, foreign_keys=ON,
busy_timeout=5000. One writer connection behind an RLock; transactions short;
no network or LLM calls inside a transaction.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

_WRITER_LOCK = threading.RLock()


def _pragmas(con: sqlite3.Connection) -> None:
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")


def _check_fts5(con: sqlite3.Connection) -> None:
    # FTS5 must be available (concern C-28).
    con.execute("CREATE VIRTUAL TABLE temp.t USING fts5(x)")
    con.execute("DROP TABLE temp.t")


class Connection:
    """A single SQLite connection with pragmas applied.

    Use :meth:`write` for mutating transactions (holds the writer lock) and
    :meth:`read` for plain queries.
    """

    def __init__(self, path: Path, readonly: bool = False):
        self._path = path
        # check_same_thread=False: one connection shared across the main/UI
        # thread and background worker/scheduler threads; all access is
        # serialized by _WRITER_LOCK in write/read/execute (plan §5.4).
        self._con = sqlite3.connect(str(self._path), isolation_level=None,
                                    check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        if readonly:
            self._con.execute("PRAGMA query_only=ON")
        _pragmas(self._con)
        _check_fts5(self._con)

    def write(self, fn):
        """Run ``fn`` inside a writer transaction (BEGIN IMMEDIATE / COMMIT)."""
        with _WRITER_LOCK:
            self._con.execute("BEGIN IMMEDIATE")
            try:
                result = fn(self._con)
                self._con.execute("COMMIT")
                return result
            except Exception:
                self._con.execute("ROLLBACK")
                raise

    def read(self, fn):
        """Run ``fn`` with read access to the connection (serialized)."""
        with _WRITER_LOCK:
            return fn(self._con)

    def execute(self, sql, parameters=()):
        """Execute ``sql`` (serialized)."""
        with _WRITER_LOCK:
            return self._con.execute(sql, parameters)

    def close(self) -> None:
        self._con.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def migrations_folder() -> Path:
    # Repo-root migrations folder (src/secretary/store/db.py -> up 3 levels = project root).
    return Path(__file__).resolve().parents[3] / "migrations"
