"""Read-only daily check for the 7-day soak: summarises secretary.log. Changes nothing.

Usage:  python scripts/soak_check.py [--days N] [path-to-secretary.log]

Reports line counts by level, ERROR lines (already redacted by the app's log filter),
main-thread watchdog stalls, scheduler ticks, reminders fired, silences longer than
5 minutes between ticks (sleep, hang or crash), the database size and the memory of a
running secretary.exe. Verdict CLEAN means no errors, stalls or silences in the window;
it does not replace looking at the app (did every reminder arrive on time?).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from secretary.paths import db_path, logs_dir

GAP_SECONDS = 5 * 60
_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_FIRED = re.compile(r"fired (\d+) reminder")


def _when(entry: dict) -> datetime | None:
    try:
        return datetime.strptime(str(entry["time"]).split(",")[0], _TIME_FORMAT)
    except (KeyError, ValueError):
        return None


def summarize(path: Path, since: datetime | None = None) -> dict | None:
    """Summary of the log at ``path`` since ``since``; ``None`` if there is no log."""
    if not path.exists():
        return None
    summary: dict = {
        "lines": 0, "unparsed": 0, "levels": {}, "errors": [], "stalls": 0,
        "ticks": 0, "reminders_fired": 0, "gaps": [], "first": None, "last": None,
    }
    previous_tick: datetime | None = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            summary["unparsed"] += 1
            continue
        when = _when(entry)
        if since is not None and when is not None and when < since:
            continue
        summary["lines"] += 1
        level = str(entry.get("level", "?"))
        message = str(entry.get("message", ""))
        summary["levels"][level] = summary["levels"].get(level, 0) + 1
        if when is not None:
            summary["first"] = summary["first"] or when
            summary["last"] = when
        if level in {"ERROR", "CRITICAL"}:
            summary["errors"].append({"time": entry.get("time"), "logger": entry.get("logger"), "message": message[:200]})
        if "GUI thread stalled" in message:
            summary["stalls"] += 1
        found = _FIRED.search(message)
        if found:
            summary["reminders_fired"] += int(found.group(1))
        if message == "scheduler tick: started":
            summary["ticks"] += 1
            if when is not None:
                if previous_tick is not None and (when - previous_tick).total_seconds() > GAP_SECONDS:
                    summary["gaps"].append({"from": previous_tick, "seconds": (when - previous_tick).total_seconds()})
                previous_tick = when
    return summary


def verdict(summary: dict) -> str:
    bad = summary["errors"] or summary["stalls"] or summary["gaps"]
    return "ATTENTION" if bad else "CLEAN"


def _memory_mb() -> str:
    """Working set of a running secretary.exe (Windows ``tasklist``); read-only."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq secretary.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    rows = [line for line in out.splitlines() if "secretary.exe" in line.lower()]
    if not rows:
        return "secretary.exe is not running"
    return "; ".join(line.split('","')[-1].strip('"') for line in rows)


def main(argv: list[str]) -> int:
    days = 1
    args = argv[1:]
    if args[:1] == ["--days"] and len(args) >= 2:
        days = int(args[1])
        args = args[2:]
    path = Path(args[0]) if args else logs_dir() / "secretary.log"
    summary = summarize(path, since=datetime.now() - timedelta(days=days))
    out = sys.stdout.write
    if summary is None:
        out(f"No log at {path}\n")
        return 2
    out(f"Window: last {days} day(s); log lines {summary['lines']} ({summary['unparsed']} unreadable)\n")
    out(f"Levels: {summary['levels']}\n")
    out(f"Scheduler ticks: {summary['ticks']}; reminders fired: {summary['reminders_fired']}\n")
    out(f"Main-thread stalls: {summary['stalls']}\n")
    for gap in summary["gaps"]:
        out(f"Silence of {gap['seconds'] / 60:.0f} min after {gap['from']:%Y-%m-%d %H:%M}\n")
    for err in summary["errors"][-10:]:
        out(f"ERROR {err['time']} {err['logger']}: {err['message']}\n")
    try:
        out(f"Database size: {db_path().stat().st_size / 1_048_576:.1f} MB\n")
    except OSError:
        out("Database size: unknown\n")
    out(f"Memory: {_memory_mb()}\n")
    out(f"Verdict: {verdict(summary)}\n")
    return 0 if verdict(summary) == "CLEAN" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
