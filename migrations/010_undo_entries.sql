CREATE TABLE undo_entries(
  id INTEGER PRIMARY KEY,
  turn_id TEXT,
  label TEXT NOT NULL,
  inverse_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  undone_at TEXT
);
CREATE INDEX idx_undo_turn ON undo_entries(turn_id);
