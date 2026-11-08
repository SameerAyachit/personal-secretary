"""Formatting resolved times for echo to the user (plan §9.4).

Every resolved time is echoed with weekday, date, time, and zone.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def format_when(dt: datetime, tz_name: str) -> str:
    """Human-friendly echo: weekday, date, time, zone."""
    zone = ZoneInfo(tz_name)
    local = dt.astimezone(zone)
    return local.strftime("%A, %d %b %Y %H:%M (%Z)")
