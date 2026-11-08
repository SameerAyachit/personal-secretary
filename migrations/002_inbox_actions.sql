CREATE TABLE inbox(
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN ('reminder','briefing','while_away','system','approval')),
  reminder_id INTEGER REFERENCES reminders(id) ON DELETE SET NULL,
  title TEXT NOT NULL, body TEXT NOT NULL,
  payload_json TEXT,
  status TEXT NOT NULL DEFAULT 'unacknowledged'
         CHECK(status IN ('unacknowledged','acknowledged','snoozed','done')),
  snoozed_until TEXT, acknowledged_at TEXT,
  last_notified_at TEXT, repeat_sent INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_inbox_status ON inbox(status, created_at);

CREATE TABLE pending_actions(
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  summary TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'waiting'
         CHECK(status IN ('waiting','approved','rejected','expired','executed','failed')),
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  decided_at TEXT, result_json TEXT
);
CREATE INDEX idx_pending_status_expires ON pending_actions(status, expires_at);

CREATE TABLE action_log(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL,
  event TEXT NOT NULL,
  entity TEXT NOT NULL, entity_id INTEGER,
  turn_id TEXT, detail_json TEXT
);
CREATE INDEX idx_log_entity ON action_log(entity, entity_id);
