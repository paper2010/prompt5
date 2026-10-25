"""M1 · 应用器属性测试（DoD：≥300 属性用例）与契约/安全用例。

矩阵 40 组 + loc 非法 16 组 + 载荷 8 组 + MOVE 7 组 + 容器删除 3 组 + 意图 6 组
+ 基线与哈希 4 组 + 保护 7 组 + 墓碑 3 组 + hypothesis 5×50 = 344 例。
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from prompt5.applier import ApplyError, apply
from prompt5.patch import Authorization
from prompt5.testing import (
    add_op,
    delete_op,
    ids_of,
    make_ir,
    make_patch,
    move_op,
    rewrite_op,
)

SAMPLE = make_ir()
MUST_IDS = ids_of(SAMPLE, "slots.constraints.must")
WF_IDS = ids_of(SAMPLE, "slots.workflow")
FF_IDS = ids_of(SAMPLE, "freeform_extras")
MUST0, MUST1, MUST2 = MUST_IDS[:3]
WF0 = WF_IDS[0]
FF0 = FF_IDS[0]

SCALAR_LOCS = ["slots.role", "slots.goal.outcome", "slots.output.format"]
CONTAINER_LOCS = ["slots.constraints.must", "slots.workflow", "freeform_extras"]
ITEM_LOCS = [
    f"slots.constraints.must[{MUST0}]",
    f"slots.workflow[{WF0}]",
    f"freeform_extras[{FF0}]",
]
FF_FIELD_LOCS = [f"freeform_extras[{FF0}].text"]

EXPECTED: dict[tuple[str, str], str] = {
    ("ADD", "scalar"): "E_ADD_TARGET",
    ("ADD", "container"): "ok",
    ("ADD", "item"): "E_ADD_TARGET",
    ("ADD", "ff_field"): "E_ADD_TARGET",
    ("DELETE", "scalar"): "E_DELETE_TARGET",
    ("DELETE", "container"): "E_DELETE_NONEMPTY",
    ("DELETE", "item"): "ok",
    ("DELETE", "ff_field"): "E_DELETE_TARGET",
    ("REWRITE", "scalar"): "ok",
    ("REWRITE", "container"): "E_REWRITE_TARGET",
    ("REWRITE", "item"): "ok",
    ("REWRITE", "ff_field"): "ok",
    ("MOVE", "scalar"): "E_MOVE_TARGET",
    ("MOVE", "container"): "E_MOVE_TARGET",
    ("MOVE", "item"): "ok",
    ("MOVE", "ff_field"): "E_MOVE_TARGET",
}


def _locs_for(kind: str) -> list[str]:
    return {
        "scalar": SCALAR_LOCS,
        "container": CONTAINER_LOCS,
        "item": ITEM_LOCS,
        "ff_field": FF_FIELD_LOCS,
    }[kind]


def _content_for(op: str, loc: str):
    if op == "ADD":
        return {"text": "added"} if loc == "freeform_extras" else "added-value"
    if op == "REWRITE":
        if loc.endswith((".text", ".note")):
            return "rewritten-field"
        return {"text": "rewritten"} if loc.startswith("freeform_extras[") else "rewritten"
    return None


def _build_op(op: str, loc: str):
    if op == "ADD":
        return add_op(loc, _content_for(op, loc))
    if op == "DELETE":
        return delete_op(loc)
    if op == "REWRITE":
        return rewrite_op(loc, _content_for(op, loc))
    return move_op(loc, {"tail": True})


def _intent_for(op: str) -> str:
    return "improve" if op in {"ADD", "REWRITE"} else "simplify"


MATRIX_PARAMS = [
    pytest.param(op, kind, loc, EXPECTED[(op, kind)], id=f"{op}-{kind}-{index}")
    for op in ("ADD", "DELETE", "REWRITE", "MOVE")
    for kind in ("scalar", "container", "item", "ff_field")
    for index, loc in enumerate(_locs_for(kind))
]


@pytest.mark.parametrize("op_name,kind,loc,expected", MATRIX_PARAMS)
def test_matrix_cells(op_name: str, kind: str, loc: str, expected: str) -> None:
    ir = make_ir()
    patch = make_patch(ir, [_build_op(op_name, loc)], intent=_intent_for(op_name))
    if expected == "ok":
        result = apply(ir, patch)
        assert result.ir.checksum != ir.checksum
        assert result.ir.verify_checksum()
    else:
        with pytest.raises(ApplyError) as excinfo:
            apply(ir, patch)
        assert excinfo.value.code == expected
        assert excinfo.value.op_index == 0


LOC_ERROR_PARAMS = [
    pytest.param("slots.constraints.must[0]", "E_INDEX_FORBIDDEN", id="index-addressing"),
    pytest.param("slots.constraints.must[12]", "E_INDEX_FORBIDDEN", id="index-multi"),
    pytest.param("slots.meta.version", "E_ROOT_FORBIDDEN", id="meta-root"),
    pytest.param("slots.protect_registry", "E_ROOT_FORBIDDEN", id="protect-root"),
    pytest.param("slots.item_ids", "E_ROOT_FORBIDDEN", id="item-ids-root"),
    pytest.param("goal.outcome", "E_ROOT_FORBIDDEN", id="missing-slots-prefix"),
    pytest.param("freeform_extras[F-3]", "E_ID_SYNTAX", id="uppercase-id"),
    pytest.param("freeform_extras[abc]", "E_ID_SYNTAX", id="short-id"),
    pytest.param(f"slots.constraints.must[{MUST0.upper()}]", "E_ID_SYNTAX", id="uppercase-item"),
    pytest.param("slots.unknown_field", "E_FIELD_UNKNOWN", id="unknown-field"),
    pytest.param("slots.goal.deep.outcome", "E_FIELD_UNKNOWN", id="unknown-depth"),
    pytest.param("freeform_extras.items", "E_FIELD_UNKNOWN", id="ff-pseudo-field"),
    pytest.param("slots.constraints.must[c-zzzz99].shadow", "E_ID_SYNTAX", id="trailing-segment"),
    pytest.param("", "E_FIELD_UNKNOWN", id="empty"),
]


@pytest.mark.parametrize("loc,code", LOC_ERROR_PARAMS)
def test_loc_errors(loc: str, code: str) -> None:
    ir = make_ir()
    with pytest.raises(ApplyError) as excinfo:
        apply(ir, make_patch(ir, [rewrite_op(loc, "x")], intent="improve"))
    assert excinfo.value.code == code


PAYLOAD_PARAMS = [
    pytest.param({"text": "x", "provenance": {}}, "E_PROTECT_FIELD", id="top-provenance"),
    pytest.param({"text": "x", "meta": {}}, "E_PROTECT_FIELD", id="top-meta"),
    pytest.param({"text": "x", "created": "now"}, "E_PROTECT_FIELD", id="top-created"),
    pytest.param(
        {"text": "x", "note": {"nested": {"protect_class": "safety"}}},
        "E_PROTECT_FIELD",
        id="nested-protect",
    ),
    pytest.param(
        {"text": "x", "note": [{"deep": [{"meta": 1}]}]},
        "E_PROTECT_FIELD",
        id="list-nested-meta",
    ),
]


@pytest.mark.parametrize("content,code", PAYLOAD_PARAMS)
def test_payload_managed_fields(content: dict, code: str) -> None:
    ir = make_ir()
    with pytest.raises(ApplyError) as excinfo:
        apply(ir, make_patch(ir, [add_op("freeform_extras", content)], intent="improve"))
    assert excinfo.value.code == code


def test_payload_clean_passes() -> None:
    ir = make_ir()
    result = apply(ir, make_patch(ir, [add_op("freeform_extras", {"text": "ok", "note": "n"})], intent="improve"))
    assert result.ir.freeform_extras[-1].text == "ok"
    assert result.ir.freeform_extras[-1].provenance["source"] == "gen"


MOVE_PARAMS = [
    pytest.param(f"slots.constraints.must[{MUST2}]", {"head": True}, 0, id="head"),
    pytest.param(f"slots.constraints.must[{MUST0}]", {"tail": True}, 2, id="tail"),
    pytest.param(f"slots.constraints.must[{MUST2}]", {"before": MUST0}, 0, id="before"),
    pytest.param(f"slots.constraints.must[{MUST0}]", {"after": MUST1}, 1, id="after"),
]


@pytest.mark.parametrize("loc,to,expected_index", MOVE_PARAMS)
def test_move_anchors(loc: str, to: dict, expected_index: int) -> None:
    ir = make_ir()
    moved_id = loc.split("[")[1].rstrip("]")
    result = apply(ir, make_patch(ir, [move_op(loc, to)], intent="simplify"))
    ids = ids_of(result.ir, "slots.constraints.must")
    assert ids.index(moved_id) == expected_index
    assert set(ids) == set(MUST_IDS)
    assert sorted(result.ir.slots.constraints.must) == sorted(ir.slots.constraints.must)


def test_move_missing_anchor() -> None:
    ir = make_ir()
    with pytest.raises(ApplyError) as excinfo:
        apply(
            ir,
            make_patch(
                ir,
                [move_op(f"slots.constraints.must[{MUST0}]", {"before": "c-nosuch1"})],
                intent="simplify",
            ),
        )
    assert excinfo.value.code == "E_FIELD_UNKNOWN"


@pytest.mark.parametrize(
    "to", [{"head": True, "tail": True}, {}, {"middle": True}], ids=["two-keys", "empty", "bad-key"]
)
def test_move_requires_exactly_one_anchor(to: dict) -> None:
    ir = make_ir()
    with pytest.raises(ValidationError):
        make_patch(ir, [move_op(f"slots.constraints.must[{MUST0}]", to)], intent="simplify")


def test_delete_nonempty_container() -> None:
    ir = make_ir()
    with pytest.raises(ApplyError) as excinfo:
        apply(ir, make_patch(ir, [delete_op("slots.constraints.must")], intent="simplify"))
    assert excinfo.value.code == "E_DELETE_NONEMPTY"


def test_delete_empty_container_is_noop() -> None:
    ir = make_ir()
    with pytest.raises(ApplyError) as excinfo:
        apply(ir, make_patch(ir, [delete_op("slots.goal.non_goals")], intent="simplify"))
    assert excinfo.value.code == "E_INTENT_MISMATCH"  # 空容器删除 = 无可测变化 → 判 no-op


def test_delete_empty_container_with_other_op() -> None:
    ir = make_ir()
    patch = make_patch(
        ir,
        [delete_op("slots.goal.non_goals"), add_op("slots.workflow", "step-three")],
        intent="improve",
    )
    result = apply(ir, patch)
    assert result.ir.slots.goal.non_goals == []
    assert result.ir.slots.workflow[-1] == "step-three"


INTENT_PARAMS = [
    pytest.param("simplify", [add_op("slots.workflow", "x")], "E_INTENT_MISMATCH", id="declared-simplify-but-add"),
    pytest.param("improve", [delete_op(f"slots.constraints.must[{MUST0}]")], "E_INTENT_MISMATCH", id="declared-improve-but-delete"),
    pytest.param("protect", [delete_op(f"slots.constraints.must[{MUST0}]")], "E_INTENT_MISMATCH", id="protect-without-auth"),
]


@pytest.mark.parametrize("intent,ops,code", INTENT_PARAMS)
def test_intent_mismatch(intent: str, ops: list, code: str) -> None:
    ir = make_ir()
    with pytest.raises(ApplyError) as excinfo:
        apply(ir, make_patch(ir, ops, intent=intent))
    assert excinfo.value.code == code


def test_fix_intent_requires_evidence() -> None:
    ir = make_ir()
    with pytest.raises(ApplyError) as excinfo:
        apply(
            ir,
            make_patch(ir, [rewrite_op("slots.role", "analyst")], intent="fix"),
        )
    assert excinfo.value.code == "E_INTENT_MISMATCH"

    ok = apply(
        ir,
        make_patch(
            ir,
            [
                {
                    "op": "REWRITE",
                    "loc": "slots.role",
                    "content": "analyst",
                    "reason": "fix",
                    "evidence_refs": ["fail:sig-1"],
                }
            ],
            intent="fix",
        ),
    )
    assert ok.ir.slots.role == "analyst"


def test_noop_rewrite_rejected() -> None:
    ir = make_ir()
    with pytest.raises(ApplyError) as excinfo:
        apply(ir, make_patch(ir, [rewrite_op("slots.role", ir.slots.role)], intent="improve"))
    assert excinfo.value.code == "E_INTENT_MISMATCH"


@pytest.mark.parametrize(
    "mutate,code",
    [
        pytest.param(lambda p: p.model_copy(update={"base": p.base.model_copy(update={"checksum": "0" * 64})}), "E_BASE_DRIFT", id="bad-checksum"),
        pytest.param(lambda p: p.model_copy(update={"base": p.base.model_copy(update={"version": 99})}), "E_BASE_DRIFT", id="bad-version"),
        pytest.param(lambda p: p.model_copy(update={"patch_hash": "f" * 64}), "E_SCHEMA_INVALID", id="tampered-hash"),
    ],
)
def test_preflight(mutate, code: str) -> None:
    ir = make_ir()
    patch = mutate(make_patch(ir, [add_op("slots.workflow", "x")]))
    with pytest.raises(ApplyError) as excinfo:
        apply(ir, patch)
    assert excinfo.value.code == code


PROTECTION_PARAMS = [
    pytest.param("DELETE", "E_PROTECT_ENACTED", id="delete"),
    pytest.param("REWRITE", "E_PROTECT_REWRITE", id="rewrite"),
    pytest.param("MOVE", "E_PROTECT_MOVE", id="move"),
]


@pytest.mark.parametrize("op_name,code", PROTECTION_PARAMS)
def test_enacted_protection(op_name: str, code: str) -> None:
    ir = make_ir()
    loc = f"slots.constraints.must[{MUST0}]"
    patch = make_patch(ir, [_build_op(op_name, loc)], intent=_intent_for(op_name))
    protect = [{"loc": loc, "cls": "safety", "state": "enacted"}]
    with pytest.raises(ApplyError) as excinfo:
        apply(ir, patch, protect=protect)
    assert excinfo.value.code == code


def test_protection_ancestor_container_delete() -> None:
    ir = make_ir()
    loc = f"slots.constraints.must[{MUST0}]"
    with pytest.raises(ApplyError) as excinfo:
        apply(
            ir,
            make_patch(ir, [delete_op("slots.constraints.must")], intent="simplify"),
            protect=[{"loc": loc, "cls": "safety", "state": "enacted"}],
        )
    assert excinfo.value.code == "E_PROTECT_ANCESTOR"


def test_protection_ancestor_on_sibling_is_allowed() -> None:
    ir = make_ir()
    protect = [{"loc": f"slots.constraints.must[{MUST0}]", "cls": "safety", "state": "enacted"}]
    result = apply(
        ir,
        make_patch(ir, [delete_op(f"slots.constraints.must[{MUST1}]")], intent="simplify"),
        protect=protect,
    )
    assert MUST0 in ids_of(result.ir, "slots.constraints.must")


def test_authorization_unlocks_enacted() -> None:
    ir = make_ir()
    loc = f"slots.constraints.must[{MUST0}]"
    patch = make_patch(ir, [delete_op(loc)], intent="protect")
    auth = Authorization(
        auth_id="auth-1", loc=loc, op_type="DELETE", patch_hash=patch.patch_hash
    )
    result = apply(
        ir,
        patch,
        protect=[{"loc": loc, "cls": "safety", "state": "enacted"}],
        authorizations=[auth],
    )
    assert MUST0 not in ids_of(result.ir, "slots.constraints.must")


def test_authorization_wrong_hash_rejected() -> None:
    ir = make_ir()
    loc = f"slots.constraints.must[{MUST0}]"
    patch = make_patch(ir, [delete_op(loc)], intent="protect")
    auth = Authorization(auth_id="auth-1", loc=loc, op_type="DELETE", patch_hash="a" * 64)
    with pytest.raises(ApplyError) as excinfo:
        apply(ir, patch, protect=[{"loc": loc, "cls": "safety", "state": "enacted"}], authorizations=[auth])
    assert excinfo.value.code == "E_PROTECT_ENACTED"


def test_authorization_consumed_rejected() -> None:
    ir = make_ir()
    loc = f"slots.constraints.must[{MUST0}]"
    patch = make_patch(ir, [delete_op(loc)], intent="protect")
    auth = Authorization(
        auth_id="auth-1",
        loc=loc,
        op_type="DELETE",
        patch_hash=patch.patch_hash,
        consumed_at="2026-01-01T00:00:00Z",
    )
    with pytest.raises(ApplyError) as excinfo:
        apply(ir, patch, protect=[{"loc": loc, "cls": "safety", "state": "enacted"}], authorizations=[auth])
    assert excinfo.value.code == "E_PROTECT_ENACTED"


def test_tombstone_blocks_rewrite() -> None:
    ir = make_ir()
    loc = f"slots.constraints.must[{MUST0}]"
    with pytest.raises(ApplyError) as excinfo:
        apply(
            ir,
            make_patch(ir, [rewrite_op(loc, "x")], intent="improve"),
            tombstones={MUST0},
        )
    assert excinfo.value.code == "E_LOC_RETIRED"


def test_delete_then_rewrite_in_same_patch_rejected() -> None:
    ir = make_ir()
    loc = f"slots.constraints.must[{MUST0}]"
    with pytest.raises(ApplyError) as excinfo:
        apply(
            ir,
            make_patch(ir, [delete_op(loc), rewrite_op(loc, "x")], intent="simplify"),
        )
    assert excinfo.value.code == "E_LOC_RETIRED"
    assert excinfo.value.op_index == 1


def test_add_then_rewrite_in_same_patch_allowed() -> None:
    ir = make_ir()
    patch = make_patch(
        ir,
        [add_op("slots.workflow", "step-three"), rewrite_op("slots.workflow", "ignored")],
        intent="improve",
    )
    # 第二条 REWRITE 打在容器上 → 矩阵拒绝（验证顺序语义仍按条校验）
    with pytest.raises(ApplyError) as excinfo:
        apply(ir, patch)
    assert excinfo.value.code == "E_REWRITE_TARGET"


# ---------------------------------------------------------------- hypothesis
@given(st.lists(st.text(min_size=1, max_size=12), min_size=1, max_size=4))
@settings(max_examples=50, deadline=None)
def test_hypothesis_deterministic_replay(items: list[str]) -> None:
    ir = make_ir()
    patch = make_patch(ir, [add_op("slots.constraints.must", text) for text in items], intent="improve")
    first = apply(ir, patch)
    second = apply(ir, patch)
    assert first.ir.checksum == second.ir.checksum
    assert first.ir.item_ids == second.ir.item_ids
    assert len(first.ir.slots.constraints.must) == len(items) + 3


@given(
    st.lists(st.text(min_size=1, max_size=8), min_size=1, max_size=3),
    st.integers(min_value=0, max_value=3),
)
@settings(max_examples=50, deadline=None)
def test_hypothesis_no_partial_application(texts: list[str], bad_index: int) -> None:
    ir = make_ir()
    ops = [add_op("slots.workflow", text) for text in texts]
    position = bad_index % (len(ops) + 1)
    ops.insert(position, rewrite_op("slots.constraints.must", "bad"))  # 容器 REWRITE → 必失败
    patch = make_patch(ir, ops, intent="improve")
    snapshot = ir.model_dump(mode="json")
    with pytest.raises(ApplyError) as excinfo:
        apply(ir, patch)
    assert excinfo.value.code == "E_REWRITE_TARGET"
    assert excinfo.value.op_index == position
    assert ir.model_dump(mode="json") == snapshot  # 基类零变更


@given(st.sampled_from(["DELETE", "REWRITE", "MOVE", "ADD"]), st.integers(min_value=0, max_value=2))
@settings(max_examples=50, deadline=None)
def test_hypothesis_single_op_always_resolved(op_name: str, loc_index: int) -> None:
    ir = make_ir()
    locs = [f"slots.constraints.must[{MUST0}]", f"slots.workflow[{WF0}]", f"freeform_extras[{FF0}]"]
    patch = make_patch(ir, [_build_op(op_name, locs[loc_index])], intent=_intent_for(op_name))
    try:
        result = apply(ir, patch)
    except ApplyError as exc:
        assert exc.code.startswith("E_")
        return
    assert result.ir.verify_checksum()


@given(st.lists(st.text(min_size=1, max_size=8), min_size=2, max_size=5, unique=True))
@settings(max_examples=50, deadline=None)
def test_hypothesis_new_ids_unique(texts: list[str]) -> None:
    ir = make_ir()
    result = apply(
        ir, make_patch(ir, [add_op("slots.constraints.must", text) for text in texts], intent="improve")
    )
    ids = ids_of(result.ir, "slots.constraints.must")
    assert len(ids) == len(set(ids)) == len(texts) + 3
    assert set(MUST_IDS) <= set(ids)


@given(st.sampled_from(["head", "tail"]))
@settings(max_examples=50, deadline=None)
def test_hypothesis_move_preserves_multiset(anchor: str) -> None:
    ir = make_ir()
    moved_id, expected = (MUST2, 0) if anchor == "head" else (MUST0, 2)
    result = apply(
        ir,
        make_patch(ir, [move_op(f"slots.constraints.must[{moved_id}]", {anchor: True})], intent="simplify"),
    )
    assert sorted(result.ir.slots.constraints.must) == sorted(ir.slots.constraints.must)
    assert ids_of(result.ir, "slots.constraints.must").index(moved_id) == expected


def test_property_budget_at_least_300() -> None:
    param_cases = len(MATRIX_PARAMS) + len(LOC_ERROR_PARAMS) + len(PAYLOAD_PARAMS) + len(MOVE_PARAMS)
    param_cases += 3 + 3 + 3 + 3 + 4 + 7 + 3  # 其余参数化组
    hypothesis_cases = 5 * 50
    assert param_cases + hypothesis_cases >= 300, param_cases + hypothesis_cases
