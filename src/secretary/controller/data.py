"""Backups, restore, export and wipe-all-data operations (plan E18)."""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

from secretary.config import load_config
from secretary.controller.llm_settings import _llm_key_name
from secretary.paths import backups_dir, db_path, logs_dir
from secretary.secrets import delete_secret
from secretary.store.backup import backup, list_backups, prune_backups, restore
from secretary.store.repos import events as events_repo
from secretary.store.repos import facts as facts_repo
from secretary.store.repos import notes as notes_repo
from secretary.store.repos import reminders as reminders_repo
from secretary.store.repos import tasks as tasks_repo

logger = logging.getLogger(__name__)


class DataMixin:
    """Backups, restore, export and wipe-all-data operations (plan E18)."""

    def list_backups(self) -> list[dict]:
        """Return available backups, newest first (Settings Data page)."""
        out: list[dict] = []
        for p in list_backups(backups_dir()):
            st = p.stat()
            out.append({"name": p.name, "path": str(p), "size": st.st_size, "mtime": st.st_mtime})
        return out

    def backup_now(self) -> dict | None:
        """Force a backup now (Settings Data 'Backup now')."""
        backups_dir().mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        dst = backups_dir() / f"secretary-{stamp}.db"
        backup(self.conn, dst)
        prune_backups(backups_dir(), load_config().backup.keep)
        return {"name": dst.name, "path": str(dst)}

    def restore_backup(self, backup_name: str) -> dict:
        """Restore a backup: stop background threads, safety-copy the current DB,
        replace it, then quit so the app restarts into the restored data
        (Settings Data 'Restore')."""
        self._stop_background()
        src = backups_dir() / backup_name
        if not src.exists():
            return {"error": "backup not found"}
        # Do not replace a database that is open.
        if self.conn is not None and self.conn._con is not None:
            with contextlib.suppress(Exception):
                self.conn.close()
        safety = restore(src, db_path())
        app = QApplication.instance()
        if app is not None:
            app.quit()
        return {"safety": str(safety), "restored": backup_name}

    def delete_all_data(self) -> dict:
        """Wipe the DB, backups, logs and Credential Manager entries, then quit
        (Settings Data 'Delete all data', plan §941)."""
        self._stop_background()
        self.conn.close()
        db = db_path()
        with contextlib.suppress(FileNotFoundError):
            db.unlink()
        for suffix in ("-wal", "-shm"):
            with contextlib.suppress(FileNotFoundError):
                Path(str(db) + suffix).unlink()
        bd = backups_dir()
        if bd.exists():
            shutil.rmtree(bd)
        ld = logs_dir()
        if ld.exists():
            # Close logging handlers before deleting the logs folder.
            for handler in logging.root.handlers[:]:
                handler.close()
                logging.root.removeHandler(handler)
            for name in logging.Logger.manager.loggerDict:
                logger_obj = logging.Logger.manager.loggerDict[name]
                if isinstance(logger_obj, logging.Logger):
                    for handler in logger_obj.handlers[:]:
                        handler.close()
                        logger_obj.removeHandler(handler)
            shutil.rmtree(ld)
        # Remove LLM keys as well as Google ones.
        delete_secret("google_token")
        delete_secret("google_client_id")
        cfg = load_config()
        for provider in list(cfg.llm.providers.keys()):
            delete_secret(_llm_key_name(provider))
        app = QApplication.instance()
        if app is not None:
            app.quit()
        return {"deleted": True}

    def _stop_background(self) -> None:
        """Stop scheduler and worker before destructive data operations."""
        if self._scheduler is not None:
            with contextlib.suppress(Exception):
                self._scheduler.stop()
        if self._worker is not None:
            with contextlib.suppress(Exception):
                self._worker.stop()

    def export_data(self, fmt: str = "json") -> dict:
        """Export tasks, reminders, events, facts and notes as JSON or Markdown
        (Settings Data 'Export', plan §942)."""
        payload = {
            "tasks": tasks_repo.list_open(self.conn),
            "reminders": reminders_repo.list_all(self.conn),
            "events": events_repo.list_window(self.conn, start_at="", end_at="9999-12-31"),
            "facts": facts_repo.list_all(self.conn),
            "notes": notes_repo.list_recent(self.conn, limit=10000),
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        backups_dir().mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        if fmt == "markdown":
            lines = ["# Secretary export", f"Generated: {payload['exported_at']}", ""]
            for section in ("tasks", "reminders", "events", "facts", "notes"):
                lines.append(f"## {section.title()}")
                for row in payload[section]:
                    lines.append("- " + " | ".join(f"{k}={v}" for k, v in row.items() if v is not None))
                lines.append("")
            text = "\n".join(lines)
            dst = backups_dir() / f"secretary-export-{stamp}.md"
            dst.write_text(text, encoding="utf-8")
        else:
            dst = backups_dir() / f"secretary-export-{stamp}.json"
            dst.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {"name": dst.name, "path": str(dst), "format": fmt}
