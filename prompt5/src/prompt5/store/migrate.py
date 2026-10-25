"""SQLite 迁移：PRAGMA user_version 驱动，幂等可重入。

M0 只建 schema v1（14 张表，见 schema.sql）。PostgreSQL 迁移在 store/pg.py（M1+）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

__all__ = ["connect", "migrate", "init_db", "SCHEMA_VERSION", "EXPECTED_TABLES"]

SCHEMA_VERSION = 1

EXPECTED_TABLES = {
    "irs",
    "tombstones",
    "patches",
    "idempotency",
    "audit_entries",
    "audit_outbox",
    "blobs",
    "tasks",
    "events",
    "sessions",
    "eval_cases",
    "model_cards",
    "protect",
    "authorizations",
}

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: str | Path, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """打开连接：WAL、外键、行工厂。`:memory:` 亦可。

    check_same_thread=False 仅供 Web 框架跨线程复用（M3 API 路径）；默认保持安全默认。
    """
    conn = sqlite3.connect(str(db_path), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None  # 显式事务：应用器提交必须由 ledger 的 BEGIN IMMEDIATE 控制
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """应用未执行的迁移，返回最终版本号。"""
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if current < 1:
        conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        current = 1
    return current


def init_db(db_path: str | Path, *, check_same_thread: bool = True) -> sqlite3.Connection:
    conn = connect(db_path, check_same_thread=check_same_thread)
    migrate(conn)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not row[0].startswith("sqlite_")
    }
    missing = EXPECTED_TABLES - tables
    if missing:
        raise RuntimeError(f"migration incomplete, missing tables: {sorted(missing)}")
    return conn
