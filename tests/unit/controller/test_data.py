"""Controller Data page: backups, restore, delete-all-data, export (plan §5.5, §941-942)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import secretary.controller.data as cm
from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import reminders as reminders_repo
from secretary.store.repos import tasks as tasks_repo


def _conn(tmp_path: Path) -> Connection:
    tmp = tmp_path / "data.db"
    conn = Connection(tmp)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn, migrations_folder(), lambda: None)
    return conn


class _FakeQApplication:
    def __init__(self, spy) -> None:
        self._spy = spy

    def instance(self):
        return self._spy


class _QuitSpy:
    def __init__(self) -> None:
        self.called = False

    def quit(self) -> None:
        self.called = True


def test_list_backups_newest_first(monkeypatch, tmp_path):
    bdir = tmp_path / "backups"
    bdir.mkdir()
    now = time.time()
    (bdir / "secretary-a.db").write_text("a")
    os.utime(bdir / "secretary-a.db", (now, now))
    (bdir / "secretary-b.db").write_text("b")
    os.utime(bdir / "secretary-b.db", (now + 1, now + 1))
    monkeypatch.setattr(cm, "backups_dir", lambda: bdir)
    controller = Controller(_conn(tmp_path))
    names = [b["name"] for b in controller.list_backups()]
    assert names == ["secretary-b.db", "secretary-a.db"]


def test_backup_now_creates_backup_file(monkeypatch, tmp_path):
    bdir = tmp_path / "backups"
    monkeypatch.setattr(cm, "backups_dir", lambda: bdir)
    controller = Controller(_conn(tmp_path))
    result = controller.backup_now()
    assert result is not None
    assert result["name"].startswith("secretary-")
    assert result["name"].endswith(".db")
    assert (bdir / result["name"]).exists()


def test_restore_backup_calls_restore_and_quits(monkeypatch, tmp_path):
    calls: list[tuple[str, str]] = []

    def fake_restore(src, dst):
        calls.append((str(src), str(dst)))
        return tmp_path / "safety.db"

    monkeypatch.setattr(cm, "restore", fake_restore)
    bdir = tmp_path / "backups"
    bdir.mkdir()
    (bdir / "secretary-1.db").write_text("x")
    monkeypatch.setattr(cm, "backups_dir", lambda: bdir)
    monkeypatch.setattr(cm, "db_path", lambda: tmp_path / "target.db")

    spy = _QuitSpy()
    monkeypatch.setattr(cm, "QApplication", _FakeQApplication(spy))

    controller = Controller(_conn(tmp_path))
    result = controller.restore_backup("secretary-1.db")
    assert calls and calls[0][0].endswith("secretary-1.db")
    assert result["restored"] == "secretary-1.db"
    assert spy.called


def test_delete_all_data_wipes_and_quits(monkeypatch, tmp_path):
    removed: list[str] = []
    rmtree_calls: list[str] = []
    delete_secret_calls: list[str] = []

    def fake_unlink(self):
        removed.append(str(self))

    def fake_rmtree(path):
        rmtree_calls.append(str(path))

    # Files/dirs must exist for the wipe to touch them.
    (tmp_path / "target.db").write_text("x")
    (tmp_path / "backups").mkdir()
    (tmp_path / "logs").mkdir()

    monkeypatch.setattr(Path, "unlink", fake_unlink)
    monkeypatch.setattr(cm.shutil, "rmtree", fake_rmtree)
    monkeypatch.setattr(cm, "backups_dir", lambda: tmp_path / "backups")
    monkeypatch.setattr(cm, "db_path", lambda: tmp_path / "target.db")
    monkeypatch.setattr(cm, "logs_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(cm, "delete_secret", delete_secret_calls.append)

    spy = _QuitSpy()
    monkeypatch.setattr(cm, "QApplication", _FakeQApplication(spy))

    controller = Controller(_conn(tmp_path))
    result = controller.delete_all_data()
    assert result["deleted"] is True
    assert any("target.db" in r for r in removed)
    assert any("backups" in r for r in rmtree_calls)
    assert any("logs" in r for r in rmtree_calls)
    assert "google_token" in delete_secret_calls and "google_client_id" in delete_secret_calls
    assert spy.called


def test_export_data_writes_json(monkeypatch, tmp_path):
    conn = _conn(tmp_path)
    tasks_repo.create(conn, title="buy groceries", source="user")
    reminders_repo.create(
        conn,
        task_id=None,
        title="drink water",
        body="",
        kind="once",
        tz="UTC",
        rule_json=None,
        next_fire_at=None,
        priority=0,
        idempotency_key=None,
        turn_id="t",
    )
    bdir = tmp_path / "backups"
    monkeypatch.setattr(cm, "backups_dir", lambda: bdir)
    written: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        cm.Path, "write_text", lambda self, text, encoding=None: written.append((self, text))
    )
    controller = Controller(conn)
    result = controller.export_data("json")
    assert result["format"] == "json"
    assert written
    data = json.loads(written[0][1])
    assert any(t["title"] == "buy groceries" for t in data["tasks"])
    assert any(r["title"] == "drink water" for r in data["reminders"])
