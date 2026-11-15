"""Task tools beyond create/list: due dates, filters, update, complete, delete (plan 8.5)."""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

import secretary.tools.tasks as tasks_module
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import tasks as tasks_repo
from secretary.tools.registry import Registry, SafetyClass
from secretary.tools.tasks import (
    register,
    task_complete,
    task_create,
    task_delete,
    task_list,
    task_update,
)

TZ = "Asia/Kolkata"


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "t.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


@pytest.fixture(autouse=True)
def _frozen_now(monkeypatch):
    monkeypatch.setattr(tasks_module, "_utc_now", lambda: datetime(2026, 11, 15, 4, 30, tzinfo=UTC))


def test_registered_with_expected_classes():
    registry = Registry()
    register(registry)
    for name in ("task_update", "task_complete", "task_delete"):
        spec = registry.get(name)
        assert spec is not None and spec.group == "core" and spec.safety_class == SafetyClass.B


def test_create_resolves_when_text_into_a_due_date():
    conn = _conn()
    try:
        out = task_create(conn, "t", {"title": "submit report", "when_text": "tomorrow at 5pm", "tz": TZ})
        row = tasks_repo.get(conn, out["task_id"])
        assert row["due_at"].startswith("2026-11-16T11:30")  # 17:00 IST in UTC
        assert row["due_tz"] == TZ
        assert "due_local" in out
    finally:
        conn.close()


def test_create_with_unparseable_when_text_asks_instead_of_dropping_it():
    conn = _conn()
    try:
        out = task_create(conn, "t", {"title": "x", "when_text": "whenever the moon is blue", "tz": TZ})
        assert "error" in out
        assert tasks_repo.list_open(conn) == []
    finally:
        conn.close()


def test_create_same_title_twice_is_deduplicated():
    conn = _conn()
    try:
        first = task_create(conn, "t1", {"title": "Buy milk"})
        second = task_create(conn, "t2", {"title": "buy MILK"})
        assert second["task_id"] == first["task_id"]
        assert len(tasks_repo.list_open(conn)) == 1
    finally:
        conn.close()


def test_list_filters():
    conn = _conn()
    try:
        task_create(conn, "t", {"title": "later", "when_text": "next week", "tz": TZ})
        task_create(conn, "t", {"title": "tomorrow thing", "when_text": "tomorrow at 9am", "tz": TZ})
        task_create(conn, "t", {"title": "no due"})
        done = task_create(conn, "t", {"title": "finished"})
        task_complete(conn, "t", {"task_ref": str(done["task_id"])})
        titles = lambda f, q=None: {x["title"] for x in task_list(conn, "t", {"filter": f, "query": q, "tz": TZ})["tasks"]}  # noqa: E731
        assert titles("open") == {"later", "tomorrow thing", "no due"}
        assert titles("tomorrow") == {"tomorrow thing"}
        assert titles("done") == {"finished"}
        assert titles("open", "milk") == set()
        assert titles("search", "due") == {"no due"}
    finally:
        conn.close()


def test_list_overdue():
    conn = _conn()
    try:
        tasks_repo.create(conn, title="old", due_at="2026-11-10T04:00:00+00:00", due_tz=TZ)
        tasks_repo.create(conn, title="future", due_at="2026-11-20T04:00:00+00:00", due_tz=TZ)
        out = task_list(conn, "t", {"filter": "overdue", "tz": TZ})
        assert [x["title"] for x in out["tasks"]] == ["old"]
    finally:
        conn.close()


def test_complete_by_id_and_by_text_fragment():
    conn = _conn()
    try:
        a = task_create(conn, "t", {"title": "call the bank"})
        b = task_create(conn, "t", {"title": "water plants"})
        assert task_complete(conn, "t", {"task_ref": str(a["task_id"])})["status"] == "done"
        out = task_complete(conn, "t", {"task_ref": "water"})
        assert out["task_id"] == b["task_id"]
        assert tasks_repo.get(conn, b["task_id"])["status"] == "done"
        assert tasks_repo.get(conn, b["task_id"])["completed_at"]
    finally:
        conn.close()


def test_ambiguous_ref_returns_candidates_and_changes_nothing():
    conn = _conn()
    try:
        task_create(conn, "t", {"title": "email Ravi"})
        task_create(conn, "t", {"title": "email Priya"})
        out = task_complete(conn, "t", {"task_ref": "email"})
        assert "candidates" in out and len(out["candidates"]) == 2
        assert all(x["status"] == "open" for x in tasks_repo.list_open(conn))
        assert len(tasks_repo.list_open(conn)) == 2
    finally:
        conn.close()


def test_unknown_ref_is_an_error():
    conn = _conn()
    try:
        assert "error" in task_complete(conn, "t", {"task_ref": "nothing like this"})
        assert "error" in task_delete(conn, "t", {"task_ref": "999"})
        assert "error" in task_update(conn, "t", {"task_ref": "999", "title": "x"})
    finally:
        conn.close()


def test_update_changes_only_given_fields():
    conn = _conn()
    try:
        made = task_create(conn, "t", {"title": "draft memo", "notes": "keep", "when_text": "tomorrow at 9am", "tz": TZ})
        out = task_update(conn, "t", {"task_ref": str(made["task_id"]), "title": "final memo", "priority": 1, "tz": TZ})
        row = tasks_repo.get(conn, made["task_id"])
        assert (row["title"], row["notes"], row["priority"]) == ("final memo", "keep", 1)
        assert row["due_at"].startswith("2026-11-16T03:30")
        assert out["title"] == "final memo"
        task_update(conn, "t", {"task_ref": str(made["task_id"]), "when_text": "next monday at 10am", "tz": TZ})
        assert tasks_repo.get(conn, made["task_id"])["due_at"].startswith("2026-11-16T04:30")
    finally:
        conn.close()


def test_update_without_any_change_is_an_error():
    conn = _conn()
    try:
        made = task_create(conn, "t", {"title": "x"})
        assert "error" in task_update(conn, "t", {"task_ref": str(made["task_id"])})
    finally:
        conn.close()


def test_delete_is_soft_and_hides_the_task():
    conn = _conn()
    try:
        made = task_create(conn, "t", {"title": "temp"})
        out = task_delete(conn, "t", {"task_ref": str(made["task_id"])})
        assert out["deleted"] is True
        assert tasks_repo.get(conn, made["task_id"]) is None
        assert tasks_repo.list_open(conn) == []
    finally:
        conn.close()
