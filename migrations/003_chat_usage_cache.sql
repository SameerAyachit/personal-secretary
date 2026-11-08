CREATE TABLE conversations(id INTEGER PRIMARY KEY, title TEXT, created_at TEXT NOT NULL, summary TEXT);
CREATE TABLE messages(
  id INTEGER PRIMARY KEY,
  conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK(role IN ('user','assistant','tool','system')),
  content TEXT NOT NULL, tool_name TEXT, tool_calls_json TEXT,
  turn_id TEXT, tokens INTEGER, created_at TEXT NOT NULL
);
CREATE INDEX idx_msg_conv ON messages(conversation_id, id);

CREATE TABLE llm_usage(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
  prompt_tokens INTEGER, completion_tokens INTEGER, latency_ms INTEGER,
  ok INTEGER NOT NULL, error TEXT, purpose TEXT
);
CREATE INDEX idx_usage_ts ON llm_usage(ts);

CREATE TABLE search_cache(
  query_hash TEXT PRIMARY KEY, query TEXT NOT NULL,
  results_json TEXT NOT NULL, fetched_at TEXT NOT NULL
);
