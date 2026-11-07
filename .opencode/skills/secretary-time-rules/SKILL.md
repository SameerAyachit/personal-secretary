---
name: secretary-time-rules
description: Use when working with dates, times, or recurrence. Covers Section 9 rules, required test cases, and forbidden patterns.
---
1. All absolute time resolution happens in `timeparse/`; the LLM only passes `when_text` / `recurrence_text`.
2. No `datetime.now()` outside the clock module (`timeparse/when.py` clock). Tests inject `now` and a timezone.
3. Recurring items: store wall-clock time plus the rrule; compute the next occurrence from the rule, never `+ timedelta` from the last fire.
4. Recurrence property tests: 7 time-zone cases, DST transitions, snooze-vs-recurrence interplay (snooze touches the inbox item only).
5. Forbidden: LLM-computed timestamps, naive datetimes crossing zones, `+` timedelta on stored fire times.
6. Run `pytest -q tests/unit/timeparse`.
