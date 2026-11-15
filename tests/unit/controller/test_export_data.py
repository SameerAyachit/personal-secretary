"""Settings > Data export includes events and notes."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import events as events_repo
from secretary.store.repos import notes as notes_repo


def test_json_export_contains_events_and_notes():
    tmp = Path(tempfile.mkdtemp()) / "x.db"
    raw = sqlite3.connect(str(tmp), isolation_level=None)
    migrate(raw, migrations_folder(), lambda: None)
    raw.close()
    conn = Connection(tmp)
    try:
        events_repo.create(conn, title="Dentist", start_at="2026-11-20T04:30:00+00:00",
                           end_at=None, tz="UTC")
        notes_repo.create(conn, text="remember the milk")
        result = Controller(conn).export_data("json")
        payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        assert [e["title"] for e in payload["events"]] == ["Dentist"]
        assert [n["text"] for n in payload["notes"]] == ["remember the milk"]
    finally:
        conn.close()
