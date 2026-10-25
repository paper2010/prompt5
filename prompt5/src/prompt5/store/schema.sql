-- prompt5 schema v1 — 来源：《搭建执行方案》§5（逐字对齐，勿擅改）
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS irs (              -- 版本台账（append-only）
  ir_id TEXT, version INTEGER, checksum TEXT, body_json TEXT,
  lineage_id TEXT, parent_version INTEGER, created_at TEXT, created_by TEXT,
  PRIMARY KEY (ir_id, version)
);

CREATE TABLE IF NOT EXISTS tombstones (        -- 墓碑：item_id 永不复用
  item_id TEXT PRIMARY KEY, loc TEXT, patch_id TEXT, at TEXT
);

CREATE TABLE IF NOT EXISTS patches (
  patch_id TEXT PRIMARY KEY, base_ir TEXT, base_version INT, base_checksum TEXT,
  model_scope TEXT, intent TEXT, ops_json TEXT, patch_hash TEXT,
  idempotency_key TEXT, status TEXT, applied_at TEXT
);

CREATE TABLE IF NOT EXISTS idempotency (       -- 唯一约束即幂等之根
  connector_id TEXT, tenant_id TEXT, op TEXT, key TEXT,
  request_hash TEXT, response_code INT, response_json TEXT,
  created_at TEXT, expires_at TEXT,
  PRIMARY KEY (connector_id, tenant_id, op, key)
);

CREATE TABLE IF NOT EXISTS audit_entries (     -- 与 IR 提交同事务；异步归档到外部 WORM
  seq INTEGER PRIMARY KEY AUTOINCREMENT, prev_hash TEXT, entry_hash TEXT,
  body_json TEXT, at TEXT
);

CREATE TABLE IF NOT EXISTS audit_outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT, seq INTEGER, state TEXT, attempts INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS blobs (
  blob_id TEXT PRIMARY KEY, tenant_id TEXT, sha256 TEXT, mime TEXT,
  size INT, path TEXT, created_at TEXT, expires_at TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY, connector_id TEXT, op TEXT, state TEXT,
  stage TEXT, result_class TEXT, fencing_token INT, envelope_json TEXT,
  rubric_state TEXT, created_at TEXT, updated_at TEXT
);

CREATE TABLE IF NOT EXISTS events (            -- 事件 outbox + DLQ
  event_id TEXT PRIMARY KEY, session_id TEXT, event_seq INT, type TEXT,
  payload_json TEXT, state TEXT, attempts INT DEFAULT 0, next_attempt_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY, ir_id TEXT, epoch INT,
  last_turn_seq INT, idle_deadline TEXT, state TEXT
);

CREATE TABLE IF NOT EXISTS eval_cases (
  case_id TEXT PRIMARY KEY, task_id TEXT, model_snapshot TEXT,
  seed INT, repeat_idx INT, results_json TEXT
);

CREATE TABLE IF NOT EXISTS model_cards (
  model_id TEXT PRIMARY KEY, card_hash TEXT, card_json TEXT,
  label TEXT, bench_version TEXT, evidence_id TEXT, achieved_at TEXT, expires_at TEXT
);

CREATE TABLE IF NOT EXISTS protect (
  loc TEXT PRIMARY KEY, cls TEXT, state TEXT, by TEXT, at TEXT, review_by TEXT
);

CREATE TABLE IF NOT EXISTS authorizations (
  auth_id TEXT PRIMARY KEY, tenant TEXT, ir_id TEXT,
  base_checksum TEXT, patch_hash TEXT, loc TEXT, op_type TEXT,
  expires_at TEXT, single_use INT, consumed_at TEXT
);
