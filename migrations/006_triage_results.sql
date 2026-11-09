CREATE TABLE triage_results(
  id INTEGER PRIMARY KEY,
  message_id INTEGER NOT NULL REFERENCES email_messages(id) ON DELETE CASCADE,
  category TEXT NOT NULL CHECK(category IN ('personal','work','newsletter','invoice','spam')),
  urgency TEXT NOT NULL CHECK(urgency IN ('low','normal','high')),
  suggested_action TEXT NOT NULL CHECK(suggested_action IN ('reply','archive','read','ignore')),
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_triage_message ON triage_results(message_id);
