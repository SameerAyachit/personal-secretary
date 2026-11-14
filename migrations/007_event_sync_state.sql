ALTER TABLE events ADD COLUMN sync_state TEXT NOT NULL DEFAULT 'synced' CHECK(sync_state IN ('synced','pending','failed'));
ALTER TABLE events ADD COLUMN sync_error TEXT;
CREATE INDEX idx_events_sync_state ON events(sync_state) WHERE sync_state <> 'synced';
