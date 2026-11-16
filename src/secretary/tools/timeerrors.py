"""Plain-language errors for time problems (plan §9.1, §8.8).

Tools return these instead of letting ``PastTime`` / ``AmbiguousTime`` escape as
raw exception text. ``error`` is for the model (what to do next); ``user_message``
is what the user may be shown when the turn has to stop.
"""

from __future__ import annotations

from secretary.timeparse.recurrence import UnparseableRecurrence
from secretary.timeparse.when import AmbiguousClock, AmbiguousTime, PastTime


def time_error(exc: Exception, when_text: str) -> dict:
    """Map a time-resolution exception to a ``{"error", "user_message"}`` result."""
    if isinstance(exc, PastTime):
        return {
            "error": (
                f"'{when_text}' is already in the past today. Do not retry the same words. "
                "Ask the user which day they mean, or call again with the day included, "
                "for example 'tomorrow 4pm'."
            ),
            "user_message": (
                f"That time ({when_text}) has already passed today. "
                "Tell me which day you mean, for example 'tomorrow at 4pm'."
            ),
        }
    if isinstance(exc, AmbiguousClock):
        return {
            "error": (
                f"'{when_text}' has an hour but no am/pm, so it could be morning or evening. "
                "Do not guess: ask the user 'AM or PM?' and call no tool, or call again with "
                "am/pm included, for example '5pm'."
            ),
            "user_message": (
                f"Did you mean {when_text} in the morning (AM) or in the evening (PM)? "
                "Tell me, for example 'at 5pm'."
            ),
        }
    if isinstance(exc, AmbiguousTime):
        return {
            "error": (
                f"Could not understand the time '{when_text}'. Ask the user to say it another "
                "way, for example 'tomorrow at 4pm' or 'in 2 hours'."
            ),
            "user_message": (
                f"I couldn't understand the time '{when_text}'. "
                "Try something like 'tomorrow at 4pm' or 'in 2 hours'."
            ),
        }
    if isinstance(exc, UnparseableRecurrence):
        return {
            "error": (
                f"Could not understand the repeat rule '{when_text}'. Ask the user, for example "
                "'every day', 'every weekday' or 'every Monday'."
            ),
            "user_message": (
                f"I couldn't understand the repeat rule '{when_text}'. "
                "Try 'every day', 'every weekday' or 'every Monday'."
            ),
        }
    return {
        "error": f"Could not resolve the time '{when_text}': {exc}",
        "user_message": f"I couldn't work out the time '{when_text}'.",
    }
