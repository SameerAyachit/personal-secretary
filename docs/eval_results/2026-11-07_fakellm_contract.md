# Secretary eval report — fake
Generated: 2026-11-08T08:31:55

Total cases: 40  |  Passed: 40  |  Failed: 0
Pass rate: 100.0%
Median latency: 0.0 ms  |  Mean latency: 0.0 ms

## Decision table (plan §7.9)
| Result | Action |
|---|---|
| ≥ 90% | Proceed with this model as primary. |
| 80-89% | Keep as primary; echo-before-write for all writes; route failures to fallback. |
| < 80% | Promote another model for write tools only; keep this one for chat and summaries; re-measure. |

## Per-category results
| Category | Passed | Total | Pass rate |
|---|---|---|---|
| ambiguous must ask | 3 | 3 | 100.0% |
| confirm-class action | 3 | 3 | 100.0% |
| create task | 6 | 6 | 100.0% |
| no tool needed | 6 | 6 | 100.0% |
| query | 6 | 6 | 100.0% |
| recurring reminder | 4 | 4 | 100.0% |
| reminder absolute/day-first | 6 | 6 | 100.0% |
| reminder relative | 6 | 6 | 100.0% |

## Case details
| ID | Category | Passed | Expected tool | Got tool | Error |
|---|---|---|---|---|---|
| create-1 | create task | YES | tasks_add | tasks_add | — |
| create-2 | create task | YES | tasks_add | tasks_add | — |
| create-3 | create task | YES | tasks_add | tasks_add | — |
| create-4 | create task | YES | tasks_add | tasks_add | — |
| create-5 | create task | YES | tasks_add | tasks_add | — |
| create-6 | create task | YES | tasks_add | tasks_add | — |
| rem-rel-1 | reminder relative | YES | reminders_add | reminders_add | — |
| rem-rel-2 | reminder relative | YES | reminders_add | reminders_add | — |
| rem-rel-3 | reminder relative | YES | reminders_add | reminders_add | — |
| rem-rel-4 | reminder relative | YES | reminders_add | reminders_add | — |
| rem-rel-5 | reminder relative | YES | reminders_add | reminders_add | — |
| rem-rel-6 | reminder relative | YES | reminders_add | reminders_add | — |
| rem-abs-1 | reminder absolute/day-first | YES | reminders_add | reminders_add | — |
| rem-abs-2 | reminder absolute/day-first | YES | reminders_add | reminders_add | — |
| rem-abs-3 | reminder absolute/day-first | YES | reminders_add | reminders_add | — |
| rem-abs-4 | reminder absolute/day-first | YES | reminders_add | reminders_add | — |
| rem-abs-5 | reminder absolute/day-first | YES | reminders_add | reminders_add | — |
| rem-abs-6 | reminder absolute/day-first | YES | reminders_add | reminders_add | — |
| recur-1 | recurring reminder | YES | reminders_add | reminders_add | — |
| recur-2 | recurring reminder | YES | reminders_add | reminders_add | — |
| recur-3 | recurring reminder | YES | reminders_add | reminders_add | — |
| recur-4 | recurring reminder | YES | reminders_add | reminders_add | — |
| query-1 | query | YES | — | — | — |
| query-2 | query | YES | — | — | — |
| query-3 | query | YES | — | — | — |
| query-4 | query | YES | — | — | — |
| query-5 | query | YES | — | — | — |
| query-6 | query | YES | — | — | — |
| none-1 | no tool needed | YES | — | — | — |
| none-2 | no tool needed | YES | — | — | — |
| none-3 | no tool needed | YES | — | — | — |
| none-4 | no tool needed | YES | — | — | — |
| none-5 | no tool needed | YES | — | — | — |
| none-6 | no tool needed | YES | — | — | — |
| confirm-1 | confirm-class action | YES | email_send | email_send | — |
| confirm-2 | confirm-class action | YES | tasks_bulk_delete | tasks_bulk_delete | — |
| confirm-3 | confirm-class action | YES | event_invite | event_invite | — |
| ambig-1 | ambiguous must ask | YES | — | — | — |
| ambig-2 | ambiguous must ask | YES | — | — | — |
| ambig-3 | ambiguous must ask | YES | — | — | — |
