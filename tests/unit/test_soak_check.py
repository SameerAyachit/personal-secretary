"""scripts/soak_check.py: a read-only summary of secretary.log for the 7-day soak."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("soak_check", ROOT / "scripts" / "soak_check.py")
soak = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(soak)

T0 = datetime(2026, 11, 16, 9, 0, 0)


def _line(offset_s: float, level: str, logger: str, message: str) -> str:
    when = (T0 + timedelta(seconds=offset_s)).strftime("%Y-%m-%d %H:%M:%S,000")
    return json.dumps({"time": when, "level": level, "logger": logger, "message": message})


def _write(tmp_path, lines):
    path = tmp_path / "secretary.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_summary_counts_levels_errors_stalls_and_reminders(tmp_path):
    path = _write(tmp_path, [
        _line(0, "INFO", "secretary.scheduler.ticker", "scheduler tick: started"),
        _line(1, "INFO", "secretary.scheduler.ticker", "scheduler tick: finished"),
        _line(30, "INFO", "secretary.scheduler.ticker", "scheduler tick: started"),
        _line(31, "INFO", "secretary.scheduler.ticker", "scheduler tick: fired 2 reminder(s)"),
        _line(60, "ERROR", "secretary.scheduler.ticker", "scheduler calendar sync failed"),
        _line(61, "WARNING", "secretary.util.main_thread_watchdog", "main-thread watchdog: GUI thread stalled for > 5.0 s; dumping"),
        "not json at all",
    ])
    summary = soak.summarize(path)
    assert summary["lines"] == 6 and summary["unparsed"] == 1
    assert summary["levels"] == {"INFO": 4, "ERROR": 1, "WARNING": 1}
    assert summary["ticks"] == 2
    assert summary["reminders_fired"] == 2
    assert summary["stalls"] == 1
    assert [e["message"] for e in summary["errors"]] == ["scheduler calendar sync failed"]


def test_long_gaps_between_scheduler_ticks_are_flagged(tmp_path):
    path = _write(tmp_path, [
        _line(0, "INFO", "secretary.scheduler.ticker", "scheduler tick: started"),
        _line(30, "INFO", "secretary.scheduler.ticker", "scheduler tick: started"),
        _line(30 + 20 * 60, "INFO", "secretary.scheduler.ticker", "scheduler tick: started"),  # 20 min silence
    ])
    summary = soak.summarize(path)
    assert len(summary["gaps"]) == 1
    assert 19 * 60 < summary["gaps"][0]["seconds"] < 21 * 60


def test_verdict_is_clean_only_without_errors_stalls_or_gaps(tmp_path):
    clean = soak.summarize(_write(tmp_path, [_line(0, "INFO", "x", "scheduler tick: started")]))
    assert soak.verdict(clean) == "CLEAN"
    bad = soak.summarize(_write(tmp_path, [_line(0, "ERROR", "x", "boom")]))
    assert soak.verdict(bad) == "ATTENTION"


def test_since_filters_old_lines(tmp_path):
    path = _write(tmp_path, [
        _line(-3 * 86400, "ERROR", "x", "old error"),
        _line(0, "INFO", "x", "recent"),
    ])
    summary = soak.summarize(path, since=T0 - timedelta(days=1))
    assert summary["errors"] == [] and summary["lines"] == 1


def test_missing_log_is_reported_not_crashed(tmp_path):
    assert soak.summarize(tmp_path / "nope.log") is None


def test_the_checker_never_opens_the_database_or_writes():
    source = (ROOT / "scripts" / "soak_check.py").read_text(encoding="utf-8")
    assert "sqlite3" not in source and "write_text" not in source and "open(" not in source.replace("Path.open", "")
