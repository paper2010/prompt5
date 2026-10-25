"""两阶段执行模型（参考实现）：前置校验 → 副本模拟 → 原子提交由 ledger 负责。

契约来源：《搭建执行方案》§4.4。本模块是**纯函数**：不读时钟、不读随机源、不碰数据库。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .ids import derive_item_id
from .ir import (
    IR,
    compute_checksum,
    list_values,
    set_in,
)
from .patch import (
    Authorization,
    LocError,
    LocTarget,
    OP_LOC_MATRIX,
    Op,
    Patch,
    _MATRIX_ERRORS,
    classify_loc,
    compute_patch_hash,
    find_managed_field,
)

__all__ = ["ApplyError", "ApplyResult", "apply"]

_OBJECT_LIST_PATHS = frozenset({"slots.inputs", "slots.examples"})


class ApplyError(Exception):
    """应用失败；code 为对外错误码，op_index 定位到具体操作（-1 表示为整包级）。"""

    def __init__(self, code: str, op_index: int | None = None, detail: str = "") -> None:
        suffix = f" @ op[{op_index}]" if op_index is not None and op_index >= 0 else ""
        super().__init__(f"{code}{suffix}" + (f": {detail}" if detail else ""))
        self.code = code
        self.op_index = op_index
        self.detail = detail

    def as_dict(self) -> dict[str, Any]:
        return {"error_code": self.code, "op_index": self.op_index, "detail": self.detail}


@dataclass
class ApplyResult:
    ir: IR
    tombstones_added: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _Ctx:
    data: dict[str, Any]
    item_ids: dict[str, list[str]]
    tombstones: set[str]
    enacted: list[dict[str, Any]]
    authorizations: Sequence[Authorization]
    patch: Patch
    tombstones_added: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    used_authorization: bool = False


def apply(
    base: IR,
    patch: Patch,
    *,
    tombstones: Iterable[str] = (),
    protect: Iterable[dict[str, Any]] = (),
    authorizations: Sequence[Authorization] = (),
) -> ApplyResult:
    """模拟执行整包补丁；任何一条失败即抛 ApplyError（不产生部分结果）。"""
    # ---- 阶段 0：前置 ----------------------------------------------------
    if patch.schema_version != base.schema_version:
        raise ApplyError("E_SCHEMA_INVALID", -1, "schema_version mismatch")
    if patch.base.ir_id != base.ir_id or patch.base.version != base.version:
        raise ApplyError("E_BASE_DRIFT", -1, "base ir_id/version mismatch")
    if patch.base.checksum != base.checksum:
        raise ApplyError("E_BASE_DRIFT", -1, "base checksum mismatch")
    if patch.patch_hash and patch.patch_hash != compute_patch_hash(patch):
        raise ApplyError("E_SCHEMA_INVALID", -1, "patch_hash does not match content")

    data = base.model_dump(mode="json", by_alias=True)
    item_ids = {path: list(ids) for path, ids in data.get("item_ids", {}).items()}
    ctx = _Ctx(
        data=data,
        item_ids=item_ids,
        tombstones=set(tombstones),
        enacted=[entry for entry in protect if entry.get("state") == "enacted"],
        authorizations=authorizations,
        patch=patch,
    )
    before_checksum = base.checksum

    # ---- 阶段 1：模拟（按序；第 N 条针对前 N-1 条之后的状态） ---------------
    for index, op in enumerate(patch.ops):
        try:
            target = classify_loc(op.loc)
            _check_tombstone(ctx, target, index)
            _check_protection(ctx, op, target, index)
            _check_matrix(op, target, index)
            _check_payload(op, index)
            _execute_op(ctx, op, target, index)
        except LocError as exc:
            raise ApplyError(exc.code, index, exc.detail) from exc

    # ---- 阶段 2：终止校验（no-op / 意图 / 模型） --------------------------
    ctx.data["item_ids"] = ctx.item_ids
    ctx.data.pop("checksum", None)
    new_checksum = compute_checksum(ctx.data)
    if new_checksum == before_checksum:
        raise ApplyError("E_INTENT_MISMATCH", -1, "no-op patch is not valid")
    _check_intent(ctx)

    ctx.data["checksum"] = new_checksum
    try:
        new_ir = IR.model_validate(ctx.data)
    except Exception as exc:  # pydantic ValidationError → 对外统一错误码
        raise ApplyError("E_SCHEMA_INVALID", -1, f"resulting IR invalid: {exc}") from exc
    if not new_ir.verify_checksum():
        raise ApplyError("E_SCHEMA_INVALID", -1, "checksum verification failed")
    return ApplyResult(
        ir=new_ir,
        tombstones_added=ctx.tombstones_added,
        events=ctx.events,
    )


# ---------------------------------------------------------------- 校验
def _check_tombstone(ctx: _Ctx, target: LocTarget, index: int) -> None:
    if target.item_id and target.item_id in ctx.tombstones:
        raise ApplyError("E_LOC_RETIRED", index, f"item {target.item_id} is tombstoned")


def _check_protection(ctx: _Ctx, op: Op, target: LocTarget, index: int) -> None:
    if not ctx.enacted:
        return
    if op.op == "ADD":
        return  # 新增不影响既有保护项（祖先保护由容器写入场景排除）
    for entry in ctx.enacted:
        enacted_loc = entry["loc"]
        if enacted_loc == op.loc:
            if _authorized(ctx, op):
                ctx.used_authorization = True
                return
            code = {
                "DELETE": "E_PROTECT_ENACTED",
                "REWRITE": "E_PROTECT_REWRITE",
                "MOVE": "E_PROTECT_MOVE",
            }[op.op]
            raise ApplyError(code, index, f"{op.op} on enacted {enacted_loc}")
        if _is_ancestor(target, enacted_loc):
            if _authorized(ctx, op):
                ctx.used_authorization = True
                return
            raise ApplyError("E_PROTECT_ANCESTOR", index, f"{op.loc} affects enacted {enacted_loc}")


def _is_ancestor(target: LocTarget, enacted_loc: str) -> bool:
    try:
        enacted = classify_loc(enacted_loc)
    except LocError:
        return False
    if enacted.path == target.path:
        # 容器操作会影响容器内的受保护项（同 item 的等值场景已在调用方处理）
        return target.kind in {"container"} and enacted.kind in {"item", "ff_field"}
    return enacted.path.startswith(target.path + ".")


def _authorized(ctx: _Ctx, op: Op) -> bool:
    if not ctx.authorizations:
        return False
    patch_hash = ctx.patch.patch_hash or compute_patch_hash(ctx.patch)
    for auth in ctx.authorizations:
        if auth.consumed_at:
            continue
        if auth.op_type != op.op or auth.loc != op.loc:
            continue
        if auth.patch_hash != patch_hash:
            continue
        return True
    return False


def _check_matrix(op: Op, target: LocTarget, index: int) -> None:
    if target.kind not in OP_LOC_MATRIX[op.op]:
        raise ApplyError(_MATRIX_ERRORS[op.op], index, f"{op.op} not allowed on {target.kind}")


def _check_payload(op: Op, index: int) -> None:
    if op.op not in {"ADD", "REWRITE"}:
        return
    if op.content is None:
        raise ApplyError("E_SCHEMA_INVALID", index, "content required")
    hit = find_managed_field(op.content)
    if hit:
        raise ApplyError("E_PROTECT_FIELD", index, f"server-managed field in payload: {hit}")


def _check_intent(ctx: _Ctx) -> None:
    kinds = {op.op for op in ctx.patch.ops}
    if ctx.used_authorization:
        expected = "protect"
    elif kinds <= {"DELETE", "MOVE"}:
        expected = "simplify"
    else:
        expected = "improve"

    if ctx.patch.intent == expected:
        return
    if (
        ctx.patch.intent == "fix"
        and kinds <= {"ADD", "REWRITE", "DELETE"}
        and all(op.evidence_refs for op in ctx.patch.ops)
    ):
        return
    raise ApplyError(
        "E_INTENT_MISMATCH",
        -1,
        f"declared {ctx.patch.intent!r} but diff implies {expected!r}",
    )


# ---------------------------------------------------------------- 执行
def _execute_op(ctx: _Ctx, op: Op, target: LocTarget, index: int) -> None:
    if op.op == "ADD":
        _do_add(ctx, op, target, index)
    elif op.op == "DELETE":
        _do_delete(ctx, op, target, index)
    elif op.op == "REWRITE":
        _do_rewrite(ctx, op, target, index)
    else:
        _do_move(ctx, op, target, index)


def _do_add(ctx: _Ctx, op: Op, target: LocTarget, index: int) -> None:
    path = target.path
    values = list_values(ctx.data, path)
    existing = {item_id for ids in ctx.item_ids.values() for item_id in ids} | ctx.tombstones
    new_id = derive_item_id(ctx.patch.patch_id, index, existing)

    if path == "freeform_extras":
        if not isinstance(op.content, dict) or not isinstance(op.content.get("text"), str):
            raise ApplyError("E_SCHEMA_INVALID", index, "freeform item requires {'text': str}")
        value = {
            "id": new_id,
            "text": op.content["text"],
            "note": op.content.get("note", ""),
            "provenance": {
                "source": "gen",
                "patch_id": ctx.patch.patch_id,
                "op_index": index,
            },
        }
    elif path in _OBJECT_LIST_PATHS:
        if not isinstance(op.content, dict):
            raise ApplyError("E_SCHEMA_INVALID", index, f"{path} requires object content")
        value = dict(op.content)
        value.pop("id", None)
    else:
        if not isinstance(op.content, str):
            raise ApplyError("E_SCHEMA_INVALID", index, f"{path} requires string content")
        value = op.content

    values.append(value)
    ctx.item_ids.setdefault(path, []).append(new_id)
    ctx.events.append({"event": "ADD", "loc": path, "item_id": new_id, "op_index": index})


def _do_delete(ctx: _Ctx, op: Op, target: LocTarget, index: int) -> None:
    path = target.path
    values = list_values(ctx.data, path)
    ids = ctx.item_ids.get(path, [])

    if target.kind == "container":
        if values:
            raise ApplyError("E_DELETE_NONEMPTY", index, f"{path} is not empty")
        ctx.events.append({"event": "DELETE_EMPTY", "loc": path, "op_index": index})
        return

    assert target.item_id is not None
    if target.item_id not in ids:
        raise ApplyError("E_FIELD_UNKNOWN", index, f"item {target.item_id} not found in {path}")
    position = ids.index(target.item_id)
    removed = values.pop(position)
    ids.pop(position)
    ctx.tombstones.add(target.item_id)
    ctx.tombstones_added.append(target.item_id)
    ctx.events.append(
        {"event": "DELETE", "loc": path, "item_id": target.item_id, "value": removed, "op_index": index}
    )


def _do_rewrite(ctx: _Ctx, op: Op, target: LocTarget, index: int) -> None:
    path = target.path

    if target.kind == "scalar":
        if path == "slots.output.schema":
            if op.content is not None and not isinstance(op.content, dict):
                raise ApplyError("E_SCHEMA_INVALID", index, "output.schema must be object or null")
        elif path == "slots.feedback_protocol":
            if not isinstance(op.content, dict):
                raise ApplyError("E_SCHEMA_INVALID", index, "feedback_protocol must be object")
        elif not isinstance(op.content, str):
            raise ApplyError("E_SCHEMA_INVALID", index, f"{path} requires string content")
        set_in(ctx.data, path, op.content)
        ctx.events.append({"event": "REWRITE", "loc": path, "op_index": index})
        return

    if target.kind == "ff_field":
        assert target.item_id is not None
        _rewrite_freeform_field(ctx, target, op.content, index)
        return

    # item
    assert target.item_id is not None
    values = list_values(ctx.data, path)
    ids = ctx.item_ids.get(path, [])
    if target.item_id not in ids:
        raise ApplyError("E_FIELD_UNKNOWN", index, f"item {target.item_id} not found in {path}")
    position = ids.index(target.item_id)

    if path == "freeform_extras":
        if not isinstance(op.content, dict) or not isinstance(op.content.get("text"), str):
            raise ApplyError("E_SCHEMA_INVALID", index, "freeform rewrite requires {'text': str}")
        values[position] = {
            "id": target.item_id,
            "text": op.content["text"],
            "note": op.content.get("note", ""),
            "provenance": {
                "source": "rewrite",
                "patch_id": ctx.patch.patch_id,
                "op_index": index,
            },
        }
    elif path in _OBJECT_LIST_PATHS:
        if not isinstance(op.content, dict):
            raise ApplyError("E_SCHEMA_INVALID", index, f"{path} requires object content")
        value = dict(op.content)
        value.pop("id", None)
        values[position] = value
    else:
        if not isinstance(op.content, str):
            raise ApplyError("E_SCHEMA_INVALID", index, f"{path} requires string content")
        values[position] = op.content
    ctx.events.append(
        {"event": "REWRITE", "loc": path, "item_id": target.item_id, "op_index": index}
    )


def _rewrite_freeform_field(ctx: _Ctx, target: LocTarget, content: Any, index: int) -> None:
    if target.field not in {"text", "note"}:
        raise ApplyError("E_FIELD_UNKNOWN", index, f"freeform field {target.field!r}")
    if not isinstance(content, str):
        raise ApplyError("E_SCHEMA_INVALID", index, f"{target.field} requires string content")
    items = ctx.data["freeform_extras"]
    for item in items:
        if item["id"] == target.item_id:
            item[target.field] = content
            item["provenance"] = {
                "source": "rewrite_field",
                "patch_id": ctx.patch.patch_id,
                "op_index": index,
            }
            ctx.events.append(
                {
                    "event": "REWRITE_FIELD",
                    "loc": f"freeform_extras[{target.item_id}].{target.field}",
                    "op_index": index,
                }
            )
            return
    raise ApplyError("E_FIELD_UNKNOWN", index, f"item {target.item_id} not found")


def _do_move(ctx: _Ctx, op: Op, target: LocTarget, index: int) -> None:
    assert target.item_id is not None and op.to is not None
    path = target.path
    values = list_values(ctx.data, path)
    ids = ctx.item_ids.get(path, [])
    if target.item_id not in ids:
        raise ApplyError("E_FIELD_UNKNOWN", index, f"item {target.item_id} not found in {path}")

    position = ids.index(target.item_id)
    value = values.pop(position)
    id_ = ids.pop(position)

    anchor_key = next(iter(op.to))
    if anchor_key == "head":
        new_position = 0
    elif anchor_key == "tail":
        new_position = len(values)
    else:
        anchor = op.to[anchor_key]
        if anchor not in ids:
            raise ApplyError("E_FIELD_UNKNOWN", index, f"MOVE anchor {anchor!r} not found")
        anchor_position = ids.index(anchor)
        new_position = anchor_position if anchor_key == "before" else anchor_position + 1

    values.insert(new_position, value)
    ids.insert(new_position, id_)
    ctx.events.append(
        {
            "event": "MOVE",
            "loc": path,
            "item_id": id_,
            "to": op.to,
            "op_index": index,
        }
    )
