-- Recurring events (ADR-007): a series is a rolling window of ordinary event rows that
-- share series_id; recurrence_json holds the rule and duration so the scheduler can top
-- the window up. Plain events keep both columns NULL.
ALTER TABLE events ADD COLUMN series_id TEXT;
ALTER TABLE events ADD COLUMN recurrence_json TEXT;
CREATE INDEX idx_events_series ON events(series_id) WHERE series_id IS NOT NULL;
