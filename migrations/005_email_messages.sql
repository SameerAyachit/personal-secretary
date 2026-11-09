CREATE TABLE email_messages(
  id INTEGER PRIMARY KEY,
  thread_id TEXT NOT NULL DEFAULT '',
  from_addr TEXT NOT NULL,
  to_addrs TEXT NOT NULL DEFAULT '[]',   -- JSON list of addresses
  subject TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL DEFAULT '',
  received_at TEXT NOT NULL,
  is_read INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'local',  -- 'local' | 'gmail' (future)
  google_message_id TEXT UNIQUE,
  deleted_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_email_messages_received ON email_messages(received_at DESC);
CREATE INDEX idx_email_messages_unread ON email_messages(is_read, received_at DESC);
