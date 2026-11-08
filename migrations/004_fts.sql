CREATE VIRTUAL TABLE search_idx USING fts5(kind, ref_id UNINDEXED, text, tokenize='unicode61');
CREATE TRIGGER trg_tasks_ai AFTER INSERT ON tasks BEGIN
  INSERT INTO search_idx(kind, ref_id, text) VALUES('task', new.id, new.title || ' ' || coalesce(new.notes,''));
END;
CREATE TRIGGER trg_tasks_au AFTER UPDATE OF title, notes ON tasks BEGIN
  DELETE FROM search_idx WHERE kind='task' AND ref_id=old.id;
  INSERT INTO search_idx(kind, ref_id, text) VALUES('task', new.id, new.title || ' ' || coalesce(new.notes,''));
END;
CREATE TRIGGER trg_tasks_ad AFTER DELETE ON tasks BEGIN
  DELETE FROM search_idx WHERE kind='task' AND ref_id=old.id;
END;
