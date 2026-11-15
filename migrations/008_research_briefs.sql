CREATE TABLE research_briefs(
  id INTEGER PRIMARY KEY,
  topic TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('running','done','failed')),
  brief TEXT NOT NULL DEFAULT '',
  sources_json TEXT NOT NULL DEFAULT '[]',
  partial INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  created_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE INDEX idx_research_briefs_created ON research_briefs(created_at DESC);
