"""Read-only report: chat-made reminders/events from before the absolute-time fix.

Before commit a4a3cc2 (2026-11-15 04:49 UTC) a clock time such as "tomorrow at 9am" was
read as UTC, so reminders and events made in chat could be hours late (5.5 h in IST).
This lists the ones made before the fix so you can check and re-set them. It changes
nothing. Usage:  python scripts/check_utc_bug.py [path-to-secretary.db]
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from secretary.paths import db_path
from secretary.store.db import Connection
from secretary.store.repos import audit

FIX_TIME_UTC = "2026-11-15T04:49:16Z"


def _local(iso: str, tz: str) -> str:
    when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(ZoneInfo(tz)).strftime("%a %d %b %H:%M")


def main(argv: list[str]) -> int:
    db = Path(argv[1]) if len(argv) > 1 else db_path()
    if not db.exists():
        sys.stdout.write(f"No database at {db}\n")
        return 1
    conn = Connection(db, readonly=True)
    try:
        found = conn.read(lambda con: audit.chat_items_before(con, FIX_TIME_UTC))
    finally:
        conn.close()
    total = 0
    for kind in ("reminders", "events"):
        sys.stdout.write(f"\n{kind.title()} made in chat before the fix and still ahead:\n")
        if not found[kind]:
            sys.stdout.write("  none\n")
        for item in found[kind]:
            total += 1
            sys.stdout.write(
                f"  #{item['id']} {item['title']!r}: stored for {_local(item['at'], item['tz'])} "
                f"({item['tz']}); created {item['created_at']}\n"
            )
    sys.stdout.write(
        f"\n{total} item(s). If a time looks 5.5 hours later than you asked, cancel and re-set it.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
