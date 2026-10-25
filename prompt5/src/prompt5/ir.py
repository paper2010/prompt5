"""IR v3：slots 单一事实源 + 列表项稳定 ID 映射。

契约来源：《搭建执行方案》§4.1/§4.3。两处补充（均记入 NOTES.md #4）：
1. 计划中 constraints.must / workflow 等为 `list[str]`，而 loc 文法要求列表项稳定 ID，
   故 IR 增加顶层 `item_ids: {list_path: [item_id, ...]}`，与各列表按下标对齐；
   初始 ID = sha256(JCS([ir_id, path, index]))[:10]。
2. `slots.output.schema` 字段名与 Pydantic 方法名冲突，落库键名保持 "schema"（alias），
   字段名用 output_schema。

checksum = sha256(JCS(payload))，payload = 除 checksum 外的全部字段（含 item_ids）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .canonical import sha256_hex
from .ids import is_valid_item_id

SCHEMA_VERSION = "3"

# 列表路径（全部需要 item_ids 对齐）
LIST_PATHS: tuple[str, ...] = (
    "slots.goal.done_criteria",
    "slots.goal.non_goals",
    "slots.constraints.must",
    "slots.constraints.must_not",
    "slots.constraints.style",
    "slots.workflow",
    "slots.inputs",
    "slots.examples",
    "freeform_extras",
)

# 标量路径（只能 REWRITE）
SCALAR_PATHS: tuple[str, ...] = (
    "slots.role",
    "slots.goal.outcome",
    "slots.output.format",
    "slots.output.schema",
    "slots.output.length_budget",
    "slots.feedback_protocol",
)

# slots 下禁止经普通 loc 触达的保留域（越权根）
FORBIDDEN_SLOT_ROOTS: frozenset[str] = frozenset(
    {
        "meta",
        "protect_registry",
        "item_ids",
        "created",
        "checksum",
        "schema_version",
        "version",
        "ir_id",
        "lineage_id",
        "parent_ir_version",
        "provenance_map",
    }
)

# 服务端管理字段：任何用户/生成器载荷中出现即拒绝（递归扫描）
SERVER_MANAGED_FIELDS: frozenset[str] = frozenset(
    {"protect_class", "provenance", "created", "meta"}
)


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Goal(_Base):
    outcome: str = ""
    done_criteria: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)


class InputRef(_Base):
    ref: str
    type: Literal["text", "json", "image", "pdf"] = "text"
    note: str = ""
    trust: Literal["user", "derived"] = "user"


class OutputSpec(_Base):
    format: str = "text"
    output_schema: dict[str, Any] | None = Field(default=None, alias="schema")
    length_budget: str = ""


class Constraints(_Base):
    must: list[str] = Field(default_factory=list)
    must_not: list[str] = Field(default_factory=list)
    style: list[str] = Field(default_factory=list)


class Example(_Base):
    input: str
    expected: str


class FreeformExtra(_Base):
    id: str
    text: str
    note: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)


class ProtectEntry(_Base):
    loc: str
    cls: Literal["safety", "hard_format", "user_pinned"]
    state: Literal["proposed", "enacted"] = "proposed"
    by: str = "system"
    at: str = ""
    review_by: str = ""


class Slots(_Base):
    role: str = ""
    goal: Goal = Field(default_factory=Goal)
    inputs: list[InputRef] = Field(default_factory=list)
    output: OutputSpec = Field(default_factory=OutputSpec)
    constraints: Constraints = Field(default_factory=Constraints)
    examples: list[Example] = Field(default_factory=list)
    workflow: list[str] = Field(default_factory=list)
    feedback_protocol: dict[str, Any] = Field(default_factory=dict)


class IR(_Base):
    schema_version: Literal["3"] = SCHEMA_VERSION
    ir_id: str
    version: int = 1
    parent_ir_version: int | None = None
    lineage_id: str
    checksum: str = ""
    created: dict[str, Any] = Field(default_factory=dict)
    slots: Slots = Field(default_factory=Slots)
    freeform_extras: list[FreeformExtra] = Field(default_factory=list)
    provenance_map: dict[str, dict] = Field(default_factory=dict)
    protect_registry: list[ProtectEntry] = Field(default_factory=list)
    item_ids: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("version")
    @classmethod
    def _version_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("version must be >= 1")
        return value

    @model_validator(mode="after")
    def _ids_aligned(self) -> "IR":
        for path in LIST_PATHS:
            values = list_values(self.model_dump(mode="json", by_alias=True), path)
            ids = self.item_ids.get(path, [])
            if len(ids) != len(values):
                raise ValueError(f"item_ids misaligned for {path}: {len(ids)} ids vs {len(values)} items")
            if len(set(ids)) != len(ids):
                raise ValueError(f"duplicate item id in {path}")
            for item_id in ids:
                if not is_valid_item_id(item_id):
                    raise ValueError(f"invalid item id {item_id!r} in {path}")
        return self

    # ---- helpers -------------------------------------------------
    def payload(self) -> dict[str, Any]:
        """除 checksum 外的规范化 dict（JCS 输入）。"""
        data = self.model_dump(mode="json", by_alias=True)
        data.pop("checksum", None)
        return data

    def compute_checksum(self) -> str:
        return compute_checksum(self.payload())

    def verify_checksum(self) -> bool:
        return self.checksum == self.compute_checksum()

    def with_checksum(self) -> "IR":
        data = self.payload()
        data["checksum"] = compute_checksum(data)
        return IR.model_validate(data)


def compute_checksum(payload_without_checksum: dict[str, Any]) -> str:
    return sha256_hex(payload_without_checksum)


# ---------------------------------------------------------------- path access
def list_values(data: dict[str, Any], path: str) -> list[Any]:
    """按 loc 路径取列表（data 为 model_dump(by_alias=True) 形态）。"""
    if path == "freeform_extras":
        return data["freeform_extras"]
    node: Any = data
    for part in path.split("."):
        node = node[part]
    if not isinstance(node, list):
        raise TypeError(f"{path} is not a list")
    return node


def get_in(data: dict[str, Any], path: str) -> Any:
    node: Any = data
    for part in path.split("."):
        node = node[part]
    return node


def set_in(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    node = data
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value


# ---------------------------------------------------------------- construction
def initial_item_ids(ir_id: str, data: dict[str, Any]) -> dict[str, list[str]]:
    """初始列表项 ID：sha256(JCS([ir_id, path, index]))[:10]，确定性且与内容无关。"""
    result: dict[str, list[str]] = {}
    for path in LIST_PATHS:
        values = list_values(data, path)
        result[path] = [sha256_hex([ir_id, path, index])[:10] for index in range(len(values))]
    return result


def build_ir(payload: dict[str, Any]) -> IR:
    """由业务载荷构造带 checksum 与 item_ids 的 IR（version 默认 1）。"""
    data = dict(payload)
    data.setdefault("version", 1)
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.pop("checksum", None)
    ids = initial_item_ids(data["ir_id"], data)
    for index, item in enumerate(data.get("freeform_extras") or []):
        if isinstance(item, dict):
            item["id"] = ids["freeform_extras"][index]
    data["item_ids"] = ids
    data["checksum"] = ""
    ir = IR.model_validate(data)
    # 关键：checksum 必须基于校验后的规范化 payload（Pydantic 会补齐默认值），
    # 否则同一语义会有两个 checksum（M1 修复项，见报告）。
    return ir.model_copy(update={"checksum": compute_checksum(ir.payload())})
