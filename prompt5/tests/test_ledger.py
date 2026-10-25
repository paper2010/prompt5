"""M1 · 台账测试：CAS 提交、版本链、墓碑、审计哈希链、回滚、授权消费。"""

from __future__ import annotations

import json

import pytest

from prompt5.applier import ApplyError
from prompt5.ledger import Ledger
from prompt5.patch import Authorization
from prompt5.store.migrate import init_db
from prompt5.testing import add_op, delete_op, ids_of, make_ir, make_patch, rewrite_op


@pytest.fixture()
def ledger():
    conn = init_db(":memory:")
    try:
        yield Ledger(conn)
    finally:
        conn.close()


def _seed(ledger: Ledger):
    ir = make_ir()
    return ledger.create_ir(ir.payload() | {"checksum": ir.checksum})


class TestCreate:
    def test_create_ir(self, ledger: Ledger) -> None:
        ir = _seed(ledger)
        assert ir.version == 1
        assert ledger.history(ir.ir_id) == [1]
        assert ledger.current(ir.ir_id).checksum == ir.checksum
        assert len(ledger.audit_entries()) == 1

    def test_duplicate_create_rejected(self, ledger: Ledger) -> None:
        ir = _seed(ledger)
        with pytest.raises(ApplyError):
            ledger.create_ir(ir.payload() | {"checksum": ir.checksum})


class TestApply:
    def test_version_increments_and_checksum_changes(self, ledger: Ledger) -> None:
        ir = _seed(ledger)
        patch = make_patch(ir, [add_op("slots.workflow", "step-three")], intent="improve")
        result = ledger.apply(patch)
        assert result.ir.version == 2
        assert result.ir.parent_ir_version == 1
        assert result.ir.checksum != ir.checksum
        assert ledger.history(ir.ir_id) == [1, 2]
        assert ledger.current(ir.ir_id).slots.workflow[-1] == "step-three"

    def test_stale_patch_rejected_without_side_effects(self, ledger: Ledger) -> None:
        ir = _seed(ledger)
        patch = make_patch(ir, [add_op("slots.workflow", "x")], intent="improve")
        ledger.apply(patch)
        audit_before = len(ledger.audit_entries())

        with pytest.raises(ApplyError) as excinfo:
            ledger.apply(patch)  # 同一 base 重放 → 基线漂移
        assert excinfo.value.code == "E_BASE_DRIFT"
        assert ledger.history(ir.ir_id) == [1, 2]
        assert len(ledger.audit_entries()) == audit_before

    def test_failed_patch_rolls_back(self, ledger: Ledger) -> None:
        ir = _seed(ledger)
        patch = make_patch(ir, [delete_op("slots.constraints.must")], intent="simplify")
        audit_before = len(ledger.audit_entries())
        with pytest.raises(ApplyError) as excinfo:
            ledger.apply(patch)
        assert excinfo.value.code == "E_DELETE_NONEMPTY"
        assert ledger.history(ir.ir_id) == [1]
        assert len(ledger.audit_entries()) == audit_before
        rows = ledger.conn.execute("SELECT COUNT(*) AS n FROM patches").fetchone()
        assert rows["n"] == 0

    def test_patch_row_recorded(self, ledger: Ledger) -> None:
        ir = _seed(ledger)
        patch = make_patch(ir, [add_op("slots.workflow", "x")], intent="improve")
        ledger.apply(patch)
        row = ledger.conn.execute("SELECT * FROM patches WHERE patch_id=?", (patch.patch_id,)).fetchone()
        assert row["status"] == "applied"
        assert row["patch_hash"] == patch.patch_hash
        assert json.loads(row["ops_json"])[0]["op"] == "ADD"


class TestTombstone:
    def test_delete_records_tombstone_and_blocks_rewrite(self, ledger: Ledger) -> None:
        ir = _seed(ledger)
        must_id = ids_of(ir, "slots.constraints.must")[0]
        loc = f"slots.constraints.must[{must_id}]"
        after_delete = ledger.apply(make_patch(ir, [delete_op(loc)], intent="simplify"))
        assert must_id in ledger.tombstones()
        assert must_id not in ids_of(after_delete.ir, "slots.constraints.must")

        retry = make_patch(
            after_delete.ir, [rewrite_op(loc, "x")], intent="improve", patch_id="01BX5ZZKBKACTAV9WEVGEMMVRZ"
        )
        with pytest.raises(ApplyError) as excinfo:
            ledger.apply(retry)
        assert excinfo.value.code == "E_LOC_RETIRED"

    def test_new_item_id_not_colliding_with_tombstone(self, ledger: Ledger) -> None:
        ir = _seed(ledger)
        result = ledger.apply(make_patch(ir, [add_op("slots.workflow", "x")], intent="improve"))
        new_id = result.ir.item_ids["slots.workflow"][-1]
        assert new_id not in ledger.tombstones()
        assert len(set(ids_of(result.ir, "slots.workflow"))) == len(ids_of(result.ir, "slots.workflow"))


class TestProtection:
    def test_enacted_blocks_and_authorization_unlocks(self, ledger: Ledger) -> None:
        ir = _seed(ledger)
        must_id = ids_of(ir, "slots.constraints.must")[0]
        loc = f"slots.constraints.must[{must_id}]"
        ledger.upsert_protect(loc, cls="safety", state="enacted")

        patch = make_patch(ir, [delete_op(loc)], intent="protect")
        with pytest.raises(ApplyError) as excinfo:
            ledger.apply(patch)
        assert excinfo.value.code == "E_PROTECT_ENACTED"

        # 授权绑定同一 patch_hash 后可执行，且授权被消费
        auth = Authorization(auth_id="auth-1", loc=loc, op_type="DELETE", patch_hash=patch.patch_hash)
        ledger.grant_authorization(auth)
        result = ledger.apply(patch)
        assert must_id not in ids_of(result.ir, "slots.constraints.must")
        remaining = ledger.authorizations(patch.patch_hash)
        assert remaining == []


class TestAuditChain:
    def test_chain_verifies_and_detects_tamper(self, ledger: Ledger) -> None:
        ir = _seed(ledger)
        ledger.apply(make_patch(ir, [add_op("slots.workflow", "x")], intent="improve"))
        assert len(ledger.audit_entries()) == 2
        assert ledger.verify_audit_chain() is True

        ledger.conn.execute(
            "UPDATE audit_entries SET body_json='{\"type\":\"forged\"}' WHERE seq=1"
        )
        assert ledger.verify_audit_chain() is False

    def test_prev_hash_links(self, ledger: Ledger) -> None:
        ir = _seed(ledger)
        ledger.apply(make_patch(ir, [add_op("slots.workflow", "x")], intent="improve"))
        entries = ledger.audit_entries()
        assert entries[1]["prev_hash"] == entries[0]["entry_hash"]
