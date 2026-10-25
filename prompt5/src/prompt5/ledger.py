"""版本台账：IR 追加、墓碑、补丁记录、审计哈希链（同事务 CAS 提交）。

契约来源：《搭建执行方案》§4.4 阶段 2、§5（DDL）、§6.3（冻结）。
并发语义：BEGIN IMMEDIATE + 提交前校验 checksum/version，不符即 E_BASE_DRIFT（零部分应用）。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Sequence

from .applier import ApplyError, ApplyResult, apply as apply_pure
from .canonical import sha256_hex
from .ir import IR, build_ir, compute_checksum
from .patch import Authorization, Patch

__all__ = ["Ledger", "LedgerResult"]

_GENESIS_HASH = "0" * 64


@dataclass
class LedgerResult:
    ir: IR
    tombstones_added: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    audit_seq: int = 0


class Ledger:
    def __init__(self, conn) -> None:
        self.conn = conn

    # ---------------------------------------------------------------- tx
    @contextmanager
    def _tx(self) -> Iterator[None]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    # ---------------------------------------------------------------- read
    def current(self, ir_id: str) -> IR:
        row = self.conn.execute(
            "SELECT body_json FROM irs WHERE ir_id=? ORDER BY version DESC LIMIT 1", (ir_id,)
        ).fetchone()
        if row is None:
            raise ApplyError("E_BASE_DRIFT", -1, f"ir {ir_id} not found")
        return IR.model_validate(json.loads(row["body_json"]))

    def history(self, ir_id: str) -> list[int]:
        rows = self.conn.execute(
            "SELECT version FROM irs WHERE ir_id=? ORDER BY version", (ir_id,)
        ).fetchall()
        return [row["version"] for row in rows]

    def tombstones(self) -> set[str]:
        return {row["item_id"] for row in self.conn.execute("SELECT item_id FROM tombstones")}

    def protect_entries(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.conn.execute("SELECT loc, cls, state, by, at, review_by FROM protect")
        ]

    def authorizations(self, patch_hash: str, only_unconsumed: bool = True) -> list[Authorization]:
        sql = "SELECT * FROM authorizations WHERE patch_hash=?"
        if only_unconsumed:
            sql += " AND consumed_at IS NULL"
        return [
            Authorization(
                auth_id=row["auth_id"],
                loc=row["loc"],
                op_type=row["op_type"],
                patch_hash=row["patch_hash"],
                expires_at=row["expires_at"] or "",
                single_use=bool(row["single_use"]),
                consumed_at=row["consumed_at"],
            )
            for row in self.conn.execute(sql, (patch_hash,))
        ]

    def audit_entries(self) -> list[Any]:
        return list(self.conn.execute("SELECT seq, prev_hash, entry_hash, body_json, at FROM audit_entries ORDER BY seq"))

    def verify_audit_chain(self) -> bool:
        prev = _GENESIS_HASH
        for row in self.audit_entries():
            body = json.loads(row["body_json"])
            expected = sha256_hex({"prev": prev, "body": body})
            if row["prev_hash"] != prev or row["entry_hash"] != expected:
                return False
            prev = expected
        return True

    # ---------------------------------------------------------------- write
    def create_ir(self, payload: dict[str, Any]) -> IR:
        ir = build_ir(payload)
        with self._tx():
            exists = self.conn.execute(
                "SELECT 1 FROM irs WHERE ir_id=?", (ir.ir_id,)
            ).fetchone()
            if exists:
                raise ApplyError("E_SCHEMA_INVALID", -1, f"ir {ir.ir_id} already exists")
            self._insert_ir(ir)
            self._append_audit(
                {
                    "type": "create",
                    "ir_id": ir.ir_id,
                    "version": ir.version,
                    "checksum": ir.checksum,
                }
            )
        return ir

    def apply(
        self,
        patch: Patch,
        authorizations: Sequence[Authorization] | None = None,
    ) -> LedgerResult:
        with self._tx():
            base = self._load_base(patch)
            auths = list(authorizations) if authorizations is not None else self.authorizations(
                patch.patch_hash
            )
            result: ApplyResult = apply_pure(
                base,
                patch,
                tombstones=self.tombstones(),
                protect=self.protect_entries(),
                authorizations=auths,
            )
            new_ir = self._bump_version(result.ir, base.version)
            self._insert_ir(new_ir)
            for item_id in result.tombstones_added:
                self.conn.execute(
                    "INSERT INTO tombstones(item_id, loc, patch_id, at) VALUES(?,?,?,?)",
                    (item_id, patch.ops[0].loc, patch.patch_id, self._now()),
                )
            self.conn.execute(
                "INSERT INTO patches(patch_id, base_ir, base_version, base_checksum, model_scope,"
                " intent, ops_json, patch_hash, idempotency_key, status, applied_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    patch.patch_id,
                    patch.base.ir_id,
                    patch.base.version,
                    patch.base.checksum,
                    patch.model_scope,
                    patch.intent,
                    json.dumps([op.model_dump(mode="json") for op in patch.ops], ensure_ascii=False),
                    patch.patch_hash,
                    patch.idempotency_key,
                    "applied",
                    self._now(),
                ),
            )
            self._consume_authorizations(patch.patch_hash)
            seq = self._append_audit(
                {
                    "type": "apply",
                    "ir_id": result.ir.ir_id,
                    "patch_id": patch.patch_id,
                    "from_version": base.version,
                    "to_version": new_ir.version,
                    "checksum_before": base.checksum,
                    "checksum_after": new_ir.checksum,
                    "tombstones": result.tombstones_added,
                    "intent": patch.intent,
                }
            )
        return LedgerResult(
            ir=new_ir,
            tombstones_added=result.tombstones_added,
            events=result.events,
            audit_seq=seq,
        )

    def upsert_protect(
        self, loc: str, cls: str, state: str = "enacted", by: str = "admin", review_by: str = ""
    ) -> None:
        with self._tx():
            self.conn.execute(
                "INSERT INTO protect(loc, cls, state, by, at, review_by) VALUES(?,?,?,?,?,?)"
                " ON CONFLICT(loc) DO UPDATE SET cls=excluded.cls, state=excluded.state,"
                " by=excluded.by, at=excluded.at, review_by=excluded.review_by",
                (loc, cls, state, by, self._now(), review_by),
            )
            self._append_audit({"type": "protect", "loc": loc, "cls": cls, "state": state})

    def grant_authorization(self, auth: Authorization) -> None:
        with self._tx():
            self.conn.execute(
                "INSERT INTO authorizations(auth_id, tenant, ir_id, base_checksum, patch_hash,"
                " loc, op_type, expires_at, single_use, consumed_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    auth.auth_id,
                    "t-001",
                    "",
                    "",
                    auth.patch_hash,
                    auth.loc,
                    auth.op_type,
                    auth.expires_at,
                    1 if auth.single_use else 0,
                    auth.consumed_at,
                ),
            )

    # ---------------------------------------------------------------- internal
    def _load_base(self, patch: Patch) -> IR:
        row = self.conn.execute(
            "SELECT version, checksum, body_json FROM irs WHERE ir_id=? ORDER BY version DESC LIMIT 1",
            (patch.base.ir_id,),
        ).fetchone()
        if row is None:
            raise ApplyError("E_BASE_DRIFT", -1, f"ir {patch.base.ir_id} not found")
        if row["version"] != patch.base.version or row["checksum"] != patch.base.checksum:
            raise ApplyError(
                "E_BASE_DRIFT",
                -1,
                f"base drift: current v{row['version']} != patch base v{patch.base.version}",
            )
        return IR.model_validate(json.loads(row["body_json"]))

    @staticmethod
    def _bump_version(ir: IR, base_version: int) -> IR:
        """应用结果 → 新版本行：version+1、parent 指向基线，并重算 checksum。"""
        data = ir.model_dump(mode="json", by_alias=True)
        data["version"] = base_version + 1
        data["parent_ir_version"] = base_version
        data.pop("checksum", None)
        data["checksum"] = compute_checksum(data)
        return IR.model_validate(data)

    def _insert_ir(self, ir: IR) -> None:
        self.conn.execute(
            "INSERT INTO irs(ir_id, version, checksum, body_json, lineage_id, parent_version,"
            " created_at, created_by) VALUES(?,?,?,?,?,?,?,?)",
            (
                ir.ir_id,
                ir.version,
                ir.checksum,
                json.dumps(ir.model_dump(mode="json", by_alias=True), ensure_ascii=False),
                ir.lineage_id,
                ir.parent_ir_version,
                self._now(),
                str(ir.created.get("by", "system")),
            ),
        )

    def _consume_authorizations(self, patch_hash: str) -> None:
        self.conn.execute(
            "UPDATE authorizations SET consumed_at=? WHERE patch_hash=? AND single_use=1"
            " AND consumed_at IS NULL",
            (self._now(), patch_hash),
        )

    def _append_audit(self, body: dict[str, Any]) -> int:
        row = self.conn.execute(
            "SELECT entry_hash FROM audit_entries ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prev = row["entry_hash"] if row else _GENESIS_HASH
        entry_hash = sha256_hex({"prev": prev, "body": body})
        cursor = self.conn.execute(
            "INSERT INTO audit_entries(prev_hash, entry_hash, body_json, at) VALUES(?,?,?,?)",
            (prev, entry_hash, json.dumps(body, ensure_ascii=False, sort_keys=True), self._now()),
        )
        self.conn.execute(
            "INSERT INTO audit_outbox(seq, state, attempts) VALUES(?,?,0)",
            (cursor.lastrowid, "pending"),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _now() -> str:
        # 台账层允许使用墙钟；应用器（纯函数）不允许。
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat(timespec="seconds")
