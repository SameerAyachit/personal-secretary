"""Backup / restore via the SQLite online backup API (plan §5.5).

Never file-copy a live DB. Backups live in the backups dir; the oldest are
pruned once ``keep`` is exceeded. Restore takes a safety copy of the current
DB before replacing it.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
import time
from pathlib import Path

from .db import Connection


def backup(source: Connection, dst: Path) -> None:
    """Online backup of ``source`` to ``dst`` (never a file copy)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst_tmp = dst.with_suffix(dst.suffix + ".tmp")
    if dst_tmp.exists():
        dst_tmp.unlink()
    dest = sqlite3.connect(str(dst_tmp))
    try:
        source._con.backup(dest)
    finally:
        dest.close()
    os.replace(dst_tmp, dst)
    return dst


def list_backups(backups_dir: Path) -> list[Path]:
    if not backups_dir.exists():
        return []
    return sorted(
        (p for p in backups_dir.glob("secretary-*.db") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def prune_backups(backups_dir: Path, keep: int) -> None:
    backups = list_backups(backups_dir)
    for old in backups[keep:]:
        with contextlib.suppress(OSError):
            old.unlink()


def last_backup_ts(settings_read) -> float | None:
    """Last backup epoch seconds, or None if never backed up."""
    try:
        v = settings_read("last_backup_at")
        if v is not None:
            return float(v)
    except Exception:
        pass
    return None


def backup_if_due(
    source: Connection,
    backups_dir: Path,
    keep: int,
    min_hours_between: int,
    settings_read,
    settings_write,
) -> Path | None:
    """Back up if ``min_hours_between`` have elapsed since the last backup."""
    now = time.time()
    last = last_backup_ts(settings_read)
    if last is not None and (now - last) < min_hours_between * 3600:
        return None
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dst = backups_dir / f"secretary-{stamp}.db"
    backup(source, dst)
    prune_backups(backups_dir, keep)
    settings_write("last_backup_at", str(now))
    return dst


def restore(src: Path, db_path: Path) -> Path:
    """Restore ``src`` into ``db_path``, keeping a safety copy of current DB."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    safety = db_path.with_suffix(db_path.suffix + f".safety-{int(time.time())}.db")
    if db_path.exists():
        shutil.copy2(db_path, safety)
    shutil.copy2(src, db_path)
    return safety
