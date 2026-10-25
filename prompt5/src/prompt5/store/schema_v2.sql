-- schema v2：在线会话所需（turns + suggestions）
CREATE TABLE IF NOT EXISTS turns (
  session_id TEXT, seq INTEGER, role TEXT, text TEXT, text_hash TEXT,
  kind TEXT, invalidates INTEGER, created_at TEXT,
  PRIMARY KEY (session_id, seq)
);

CREATE TABLE IF NOT EXISTS suggestions (
  suggestion_id TEXT PRIMARY KEY, session_id TEXT, patch_json TEXT, patch_hash TEXT,
  epoch INTEGER, base_checksum TEXT, intent_hash TEXT, context_hash TEXT,
  state TEXT, created_at TEXT, applied_at TEXT
);
