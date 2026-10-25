"""M1 · IR/Patch 契约测试：checksum、item_ids 对齐、loc 文法、op 校验、patch_hash。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from prompt5.ir import LIST_PATHS, build_ir, compute_checksum, list_values
from prompt5.patch import Patch, classify_loc, compute_patch_hash, find_managed_field
from prompt5.testing import add_op, ids_of, make_ir, make_patch


class TestIR:
    def test_checksum_verifies(self) -> None:
        ir = make_ir()
        assert ir.verify_checksum()
        assert ir.checksum == compute_checksum(ir.payload())

    def test_item_ids_aligned_with_lists(self) -> None:
        ir = make_ir()
        data = ir.model_dump(mode="json", by_alias=True)
        for path in LIST_PATHS:
            assert len(ir.item_ids[path]) == len(list_values(data, path)), path
        assert len(ir.item_ids["slots.constraints.must"]) == len(ir.slots.constraints.must)

    def test_freeform_id_matches_item_ids(self) -> None:
        ir = make_ir()
        assert ir.freeform_extras[0].id == ir.item_ids["freeform_extras"][0]

    def test_tamper_breaks_checksum(self) -> None:
        ir = make_ir()
        data = ir.model_dump(mode="json", by_alias=True)
        data["slots"]["constraints"]["must"][0] = "tampered"
        data["checksum"] = compute_checksum({k: v for k, v in data.items() if k != "checksum"})
        from prompt5.ir import IR

        forged = IR.model_validate(data)
        assert forged.verify_checksum()  # 重算后会一致，但 checksum 已变
        assert forged.checksum != ir.checksum

    def test_rejects_duplicate_ids(self) -> None:
        ir = make_ir()
        data = ir.model_dump(mode="json", by_alias=True)
        data["item_ids"]["slots.workflow"][1] = data["item_ids"]["slots.workflow"][0]
        from prompt5.ir import IR

        with pytest.raises(ValidationError):
            IR.model_validate(data)


class TestClassifyLoc:
    @pytest.mark.parametrize(
        "loc,kind",
        [
            ("slots.role", "scalar"),
            ("slots.goal.outcome", "scalar"),
            ("slots.output.schema", "scalar"),
            ("slots.constraints.must", "container"),
            ("slots.workflow", "container"),
            ("freeform_extras", "container"),
        ],
    )
    def test_scalar_and_container(self, loc: str, kind: str) -> None:
        assert classify_loc(loc).kind == kind

    def test_item_and_field(self) -> None:
        ir = make_ir()
        must_id = ids_of(ir, "slots.constraints.must")[0]
        ff_id = ids_of(ir, "freeform_extras")[0]
        target = classify_loc(f"slots.constraints.must[{must_id}]")
        assert target.kind == "item" and target.item_id == must_id
        ff = classify_loc(f"freeform_extras[{ff_id}].note")
        assert ff.kind == "ff_field" and ff.field == "note"


class TestOpValidation:
    def test_move_requires_anchor(self) -> None:
        ir = make_ir()
        with pytest.raises(ValidationError):
            make_patch(ir, [{"op": "MOVE", "loc": "slots.workflow", "reason": "r"}], intent="simplify")

    def test_delete_requires_evidence(self) -> None:
        ir = make_ir()
        with pytest.raises(ValidationError):
            make_patch(ir, [{"op": "DELETE", "loc": "slots.workflow", "reason": "r"}], intent="simplify")

    def test_non_move_rejects_to(self) -> None:
        ir = make_ir()
        with pytest.raises(ValidationError):
            make_patch(
                ir,
                [{"op": "ADD", "loc": "slots.workflow", "content": "x", "to": {"head": True}}],
                intent="improve",
            )

    def test_empty_ops_rejected(self) -> None:
        ir = make_ir()
        with pytest.raises(ValidationError):
            make_patch(ir, [], intent="improve")


class TestPatchHash:
    def test_hash_excludes_patch_id_and_hash(self) -> None:
        ir = make_ir()
        first = make_patch(ir, [add_op("slots.workflow", "x")])
        second = make_patch(ir, [add_op("slots.workflow", "x")], patch_id="01BX5ZZKBKACTAV9WEVGEMMVRZ")
        assert first.patch_hash == second.patch_hash

    def test_hash_changes_with_content(self) -> None:
        ir = make_ir()
        first = make_patch(ir, [add_op("slots.workflow", "x")])
        second = make_patch(ir, [add_op("slots.workflow", "y")])
        assert first.patch_hash != second.patch_hash

    def test_hash_matches_model_method(self) -> None:
        ir = make_ir()
        patch = make_patch(ir, [add_op("slots.workflow", "x")])
        assert patch.patch_hash == compute_patch_hash(patch)


class TestManagedFieldScan:
    @pytest.mark.parametrize(
        "payload,expected",
        [
            ({"text": "ok"}, None),
            ({"provenance": {}}, "provenance"),
            ({"a": {"b": {"meta": 1}}}, "a.b.meta"),
            ([{"deep": [{"created": 1}]}], "[0].deep[0].created"),
        ],
    )
    def test_scan(self, payload, expected) -> None:
        assert find_managed_field(payload) == expected


def test_build_ir_rejects_unknown_field() -> None:
    ir = make_ir()
    data = ir.model_dump(mode="json", by_alias=True)
    data["slots"]["unexpected"] = 1
    with pytest.raises(ValidationError):
        build_ir(data)
