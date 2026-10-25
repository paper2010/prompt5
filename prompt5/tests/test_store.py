"""M0 · store 测试：迁移幂等、14 表齐全、幂等唯一约束、审计自增。"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from prompt5.store.migrate import (
    EXPECTED_TABLES,
    SCHEMA_VERSION,
    connect,
    init_db,
    migrate,
)


class MigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "prompt5.db"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_creates_all_tables(self) -> None:
        conn = init_db(self.db_path)
        try:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                if not row[0].startswith("sqlite_")
            }
        finally:
            conn.close()
        self.assertEqual(tables, EXPECTED_TABLES)
        self.assertEqual(len(tables), 16)

    def test_user_version_stamped(self) -> None:
        conn = init_db(self.db_path)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(version, SCHEMA_VERSION)

    def test_migrate_is_idempotent(self) -> None:
        conn = connect(self.db_path)
        try:
            self.assertEqual(migrate(conn), 2)
            self.assertEqual(migrate(conn), 2)  # 二次调用不重建、不报错
        finally:
            conn.close()


class ConstraintTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = init_db(":memory:")

    def tearDown(self) -> None:
        self.conn.close()

    def test_idempotency_unique_key(self) -> None:
        row = ("conn-1", "t-001", "generate.v1", "idem-abc", "hash", 200, "{}", "now", "later")
        self.conn.execute(
            "INSERT INTO idempotency(connector_id, tenant_id, op, key, request_hash,"
            " response_code, response_json, created_at, expires_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            row,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO idempotency(connector_id, tenant_id, op, key, request_hash,"
                " response_code, response_json, created_at, expires_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                row,
            )

    def test_audit_entries_auto_increment(self) -> None:
        for idx in range(2):
            self.conn.execute(
                "INSERT INTO audit_entries(prev_hash, entry_hash, body_json, at)"
                " VALUES(?,?,?,?)",
                ("0" * 64 if idx == 0 else "a" * 64, "b" * 64, "{}", "now"),
            )
        seqs = [row[0] for row in self.conn.execute("SELECT seq FROM audit_entries ORDER BY seq")]
        self.assertEqual(seqs, [1, 2])

    def test_tombstone_primary_key(self) -> None:
        self.conn.execute(
            "INSERT INTO tombstones(item_id, loc, patch_id, at) VALUES(?,?,?,?)",
            ("c-aaaa11", "slots.constraints.must[c-aaaa11]", "pid", "now"),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO tombstones(item_id, loc, patch_id, at) VALUES(?,?,?,?)",
                ("c-aaaa11", "other", "pid2", "now"),
            )


if __name__ == "__main__":
    unittest.main()
