CREATE TABLE notes(
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT
);
CREATE INDEX idx_notes_created ON notes(created_at DESC);
