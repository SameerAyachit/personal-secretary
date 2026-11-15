"""note_add / note_search tools and the notes repo (plan 8.5)."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import notes as notes_repo
from secretary.tools.notes import note_add, note_search, register
from secretary.tools.registry import Registry, SafetyClass


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "n.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    return Connection(tmp)


def test_registered_in_core_group_with_expected_classes():
    registry = Registry()
    register(registry)
    add, search = registry.get("note_add"), registry.get("note_search")
    assert add.group == search.group == "core"
    assert add.safety_class == SafetyClass.B and search.safety_class == SafetyClass.A


def test_add_then_search_finds_the_note():
    conn = _conn()
    try:
        out = note_add(conn, "t", {"text": "Wi-Fi password for the flat is on the fridge"})
        assert out["note_id"] > 0
        found = note_search(conn, "t", {"query": "wi-fi"})["notes"]
        assert [n["id"] for n in found] == [out["note_id"]]
        assert "fridge" in found[0]["text"]
        assert note_search(conn, "t", {"query": "passport"})["notes"] == []
    finally:
        conn.close()


def test_search_treats_wildcards_literally_and_returns_newest_first():
    conn = _conn()
    try:
        note_add(conn, "t1", {"text": "100% done"})
        note_add(conn, "t2", {"text": "100 things"})
        assert [n["text"] for n in note_search(conn, "t", {"query": "100%"})["notes"]] == ["100% done"]
        note_add(conn, "t3", {"text": "alpha one"})
        note_add(conn, "t4", {"text": "alpha two"})
        assert [n["text"] for n in note_search(conn, "t", {"query": "alpha"})["notes"]] == ["alpha two", "alpha one"]
    finally:
        conn.close()


def test_blank_text_is_rejected_and_same_note_twice_is_deduplicated():
    conn = _conn()
    try:
        assert "error" in note_add(conn, "t", {"text": "   "})
        first = note_add(conn, "t1", {"text": "buy stamps"})
        second = note_add(conn, "t2", {"text": "Buy Stamps"})
        assert second["note_id"] == first["note_id"]
        assert len(notes_repo.list_recent(conn)) == 1
    finally:
        conn.close()


def test_empty_query_lists_recent_notes():
    conn = _conn()
    try:
        note_add(conn, "t", {"text": "one"})
        assert len(note_search(conn, "t", {"query": ""})["notes"]) == 1
    finally:
        conn.close()
