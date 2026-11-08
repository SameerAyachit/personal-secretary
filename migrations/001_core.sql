CREATE TABLE tasks(
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  notes TEXT,
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','done','cancelled')),
  priority INTEGER NOT NULL DEFAULT 0,
  due_at TEXT, due_tz TEXT,
  source TEXT NOT NULL DEFAULT 'user' CHECK(source IN ('user','agent','email','calendar')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  completed_at TEXT, deleted_at TEXT
);
CREATE INDEX idx_tasks_status_due ON tasks(status, due_at);

CREATE TABLE reminders(
  id INTEGER PRIMARY KEY,
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
  title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL CHECK(kind IN ('once','recurring')),
  tz TEXT NOT NULL,
  rule_json TEXT,
  next_fire_at TEXT,
  status TEXT NOT NULL DEFAULT 'scheduled'
         CHECK(status IN ('scheduled','firing','done','cancelled')),
  priority INTEGER NOT NULL DEFAULT 0,
  idempotency_key TEXT UNIQUE,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT
);
CREATE INDEX idx_rem_due ON reminders(status, next_fire_at);

CREATE TABLE reminder_runs(
  id INTEGER PRIMARY KEY,
  reminder_id INTEGER NOT NULL REFERENCES reminders(id) ON DELETE CASCADE,
  scheduled_for TEXT NOT NULL,
  fired_at TEXT,
  outcome TEXT NOT NULL CHECK(outcome IN ('fired','missed','grouped')),
  UNIQUE(reminder_id, scheduled_for)
);

CREATE TABLE events(
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL, start_at TEXT NOT NULL, end_at TEXT, tz TEXT NOT NULL,
  all_day INTEGER NOT NULL DEFAULT 0, location TEXT, notes TEXT,
  google_event_id TEXT UNIQUE, etag TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT
);
CREATE INDEX idx_events_start ON events(start_at);

CREATE TABLE facts(
  id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, value TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
