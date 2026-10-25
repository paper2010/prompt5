"""Patch v3 契约：loc 文法解析、op-loc 兼容矩阵、意图与授权。

来源：《搭建执行方案》§4.2/§4.3。
uncovered 说明（NOTES.md #4）：`ADD` 载荷若携带 `id` 字段一律忽略并由服务端重新分配，
不做报错（避免客户端猜测 ID 规则）；`provenance` 属服务端管理字段，出现即 E_PROTECT_FIELD。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .canonical import sha256_hex
from .ir import (
    FORBIDDEN_SLOT_ROOTS,
    LIST_PATHS,
    SCALAR_PATHS,
    SERVER_MANAGED_FIELDS,
)

__all__ = [
    "Op",
    "Patch",
    "BaseRef",
    "Authorization",
    "LocTarget",
    "LocError",
    "classify_loc",
    "compute_patch_hash",
    "iter_payload_fields",
    "OP_LOC_MATRIX",
]

ITEM_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{4,14}[a-z0-9]$")
_INDEX_RE = re.compile(r"^\d+$")
_FF_RE = re.compile(r"^freeform_extras\[([^\]]+)\](?:\.(text|note))?$")
_SLOT_ITEM_RE = re.compile(r"^([a-z0-9_.]+)\[([^\]]+)\]$")


class LocError(ValueError):
    """loc 非法；code 为对外错误码。"""

    def __init__(self, code: str, loc: str = "", detail: str = "") -> None:
        super().__init__(f"{code}: {loc} {detail}".strip())
        self.code = code
        self.loc = loc
        self.detail = detail


@dataclass(frozen=True)
class LocTarget:
    kind: Literal["scalar", "container", "item", "ff_field"]
    path: str                      # 容器/标量路径，如 slots.constraints.must
    item_id: str | None = None
    field: str | None = None       # 仅 ff_field：text / note

    @property
    def normalized(self) -> str:
        return f"{self.path}[{self.item_id}]" if self.item_id else self.path


def _validate_item_id(raw: str, loc: str) -> str:
    if _INDEX_RE.match(raw):
        raise LocError("E_INDEX_FORBIDDEN", loc, "index addressing is forbidden")
    if not ITEM_ID_RE.match(raw):
        raise LocError("E_ID_SYNTAX", loc, f"invalid item_id {raw!r}")
    return raw


def classify_loc(loc: str) -> LocTarget:
    """按 §4.3 文法解析 loc，返回目标类型；非法即抛 LocError（带错误码）。"""
    loc = loc.strip()
    if not loc:
        raise LocError("E_FIELD_UNKNOWN", loc, "empty loc")

    if loc == "freeform_extras":
        return LocTarget(kind="container", path="freeform_extras")

    if loc.startswith("freeform_extras"):
        match = _FF_RE.match(loc)
        if not match:
            if _INDEX_RE.match(loc[len("freeform_extras"):].strip("[]")):
                raise LocError("E_INDEX_FORBIDDEN", loc)
            raise LocError("E_FIELD_UNKNOWN", loc)
        item_id = _validate_item_id(match.group(1), loc)
        field = match.group(2)
        if field:
            return LocTarget(kind="ff_field", path="freeform_extras", item_id=item_id, field=field)
        return LocTarget(kind="item", path="freeform_extras", item_id=item_id)

    if not loc.startswith("slots."):
        raise LocError("E_ROOT_FORBIDDEN", loc, "loc root must be slots or freeform_extras")

    body = loc[len("slots."):]
    head = body.split(".", 1)[0].split("[", 1)[0]
    if head in FORBIDDEN_SLOT_ROOTS:
        raise LocError("E_ROOT_FORBIDDEN", loc, f"reserved subtree {head!r}")

    item_match = _SLOT_ITEM_RE.match(body)
    if item_match:
        path = f"slots.{item_match.group(1)}"
        item_id = _validate_item_id(item_match.group(2), loc)
        if path not in LIST_PATHS:
            raise LocError("E_FIELD_UNKNOWN", loc, f"{path} is not an addressable list")
        return LocTarget(kind="item", path=path, item_id=item_id)

    if "[" in body or "]" in body:
        bracket = body[body.find("["):]
        if _INDEX_RE.match(bracket.strip("[]")):
            raise LocError("E_INDEX_FORBIDDEN", loc)
        raise LocError("E_ID_SYNTAX", loc)

    path = f"slots.{body}"
    if path in LIST_PATHS:
        return LocTarget(kind="container", path=path)
    if path in SCALAR_PATHS:
        return LocTarget(kind="scalar", path=path)
    raise LocError("E_FIELD_UNKNOWN", loc, f"{path} unknown")


# 16 格兼容矩阵：合法=集合中的 (op, kind)，其余按 _MATRIX_ERRORS 报错
OP_LOC_MATRIX: dict[str, set[str]] = {
    "ADD": {"container"},
    "DELETE": {"container", "item"},   # container 仅限空容器，由应用器二次判定
    "REWRITE": {"scalar", "item", "ff_field"},
    "MOVE": {"item"},
}

_MATRIX_ERRORS: dict[str, str] = {
    "ADD": "E_ADD_TARGET",
    "DELETE": "E_DELETE_TARGET",
    "REWRITE": "E_REWRITE_TARGET",
    "MOVE": "E_MOVE_TARGET",
}


class BaseRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ir_id: str
    version: int
    checksum: str


class Op(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["ADD", "DELETE", "REWRITE", "MOVE"]
    loc: str
    content: Any = None
    reason: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    to: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> "Op":
        if self.op == "MOVE":
            if not self.to or set(self.to) not in ({"head"}, {"tail"}, {"before"}, {"after"}):
                raise ValueError("MOVE requires exactly one of to.head/to.tail/to.before/to.after")
        elif self.to is not None:
            raise ValueError("to is only valid for MOVE")
        if self.op in {"ADD", "REWRITE"} and self.content is None:
            raise ValueError(f"{self.op} requires content")
        if self.op == "DELETE" and not self.evidence_refs:
            raise ValueError("DELETE requires non-empty evidence_refs")
        return self


class Patch(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["3"] = "3"
    patch_id: str
    base: BaseRef
    model_scope: str | None = None
    intent: Literal["improve", "simplify", "fix", "protect"]
    ops: list[Op] = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    created: dict[str, Any] = Field(default_factory=dict)
    patch_hash: str = ""

    def compute_hash(self) -> str:
        data = self.model_dump(mode="json", by_alias=True)
        data.pop("patch_hash", None)
        data.pop("patch_id", None)
        return sha256_hex(data)


def compute_patch_hash(patch: Patch) -> str:
    return patch.compute_hash()


# ---------------------------------------------------------------- authorizations
class Authorization(BaseModel):
    """保护类授权：绑定 loc/op_type/patch_hash，单次消费（消费状态由台账维护）。"""

    model_config = ConfigDict(extra="forbid")

    auth_id: str
    loc: str
    op_type: Literal["ADD", "DELETE", "REWRITE", "MOVE"]
    patch_hash: str
    expires_at: str = ""
    single_use: bool = True
    consumed_at: str | None = None


def iter_payload_fields(content: Any, path: str = ""):
    """递归产出 (字段路径, 键名)，供服务端管理字段扫描使用。"""
    if isinstance(content, dict):
        for key, value in content.items():
            yield f"{path}.{key}".lstrip("."), key
            yield from iter_payload_fields(value, f"{path}.{key}")
    elif isinstance(content, list):
        for index, value in enumerate(content):
            yield from iter_payload_fields(value, f"{path}[{index}]")


def find_managed_field(content: Any) -> str | None:
    for field_path, key in iter_payload_fields(content):
        if key in SERVER_MANAGED_FIELDS:
            return field_path
    return None
