"""Tests for core task tools (plan §8.5)."""

import sqlite3
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.tools.idempotency import idempotency_key
from secretary.tools.tasks import TaskCreateArgs, task_create, task_list


def _conn():
    tmp = Path(tempfile.mkdtemp()) / "t.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")

    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


def test_task_create_args_validation():
    args = TaskCreateArgs(title="buy milk", when_text="tomorrow", priority=1)
    assert args.title == "buy milk"
    assert args.when_text == "tomorrow"
    assert args.priority == 1

    with pytest.raises(ValidationError):
        TaskCreateArgs()  # title required


def test_task_create_executes_and_returns_idempotency_key():
    conn = _conn()
    try:
        turn_id = "turn-1"
        result = task_create(conn, turn_id, {"title": "buy milk", "when_text": "tomorrow"})
        assert "task_id" in result
        assert result["title"] == "buy milk"
        assert result["idempotency_key"] == idempotency_key(
            turn_id, "task_create", {"title": "buy milk", "notes": "", "when_text": "tomorrow", "priority": 0}
        )
        # Idempotent: same turn+tool+args returns same key.
        result2 = task_create(conn, turn_id, {"title": "buy milk", "when_text": "tomorrow"})
        assert result2["idempotency_key"] == result["idempotency_key"]
    finally:
        conn.close()


def test_task_list_executes():
    conn = _conn()
    try:
        task_create(conn, "turn-1", {"title": "task one"})
        task_create(conn, "turn-1", {"title": "task two"})
        result = task_list(conn, "turn-1", {"filter": "open"})
        assert len(result["tasks"]) == 2
        titles = {t["title"] for t in result["tasks"]}
        assert titles == {"task one", "task two"}
    finally:
        conn.close()
