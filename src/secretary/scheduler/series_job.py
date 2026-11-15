"""Keep recurring events topped up (ADR-007).

Runs as a step of the scheduler tick. For every series that still has a live
occurrence, adds the occurrences that now fall inside the rolling window. Safe to
run on every tick: nothing is added when the window is already full.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from secretary.store.db import Connection
from secretary.store.repos import events as events_repo
from secretary.timeparse.recurrence import RecurrenceRule
from secretary.tools.event_series import (
    HORIZON_DAYS,
    MAX_OCCURRENCES,
    insert_occurrences,
    occurrences_after,
)

logger = logging.getLogger(__name__)


def extend_series(conn: Connection, now: datetime | None = None, horizon_days: int = HORIZON_DAYS) -> int:
    """Add missing occurrences to every live series; returns how many rows were created."""
    now = now or datetime.now(UTC)
    horizon_end = now + timedelta(days=horizon_days)
    created = 0
    for item in conn.read(events_repo.series_overview):
        template = item["template"]
        try:
            meta = json.loads(template["recurrence_json"])
            rule = RecurrenceRule.from_json(meta["rule"])
            duration = int(meta["duration_minutes"])
            last = datetime.fromisoformat(item["last_start"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("series %s has unreadable recurrence data; skipped", item["series_id"])
            continue
        starts = occurrences_after(rule, last, horizon_end, MAX_OCCURRENCES)
        if not starts:
            continue
        conn.write(
            lambda con, t=template, s=starts, r=rule, d=duration: insert_occurrences(
                con, title=t["title"], starts=s, duration_minutes=d, tz=t["tz"],
                location=t.get("location"), series_id=t["series_id"], rule=r, turn_id="series-topup",
            )
        )
        created += len(starts)
    if created:
        logger.info("series top-up: added %d occurrence(s)", created)
    return created
