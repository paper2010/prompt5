"""对外请求/响应契约（TaskRequest / EvalEvidence），仅用于 JSON Schema 导出与校验。

来源：《搭建执行方案》§7.2（材料接入后的 TaskRequest）、§9.5（裁判证据链）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["TaskRequest", "EvalEvidence", "DialogueTurn", "MaterialRef", "JudgeRef"]


class DialogueTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn: int = Field(ge=1)
    role: Literal["user", "assistant", "system"]
    text: str
    content_hash: str | None = None


class MaterialRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blob_id: str = Field(min_length=1)


class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["zero", "seed"] = "zero"
    dialogue: list[DialogueTurn] = Field(default_factory=list)
    materials: list[MaterialRef] = Field(default_factory=list, max_length=20)
    target_model: str
    rubric_policy: Literal["draft_then_confirm"] = "draft_then_confirm"
    seed_text: str | None = None
    parent_ir_id: str | None = None


class TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_version: Literal["1"] = "1"
    request_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    op: Literal["generate.v1", "iterate.v1"]
    input: TaskInput
    budget_hint: dict[str, Any] = Field(default_factory=dict)
    extensions: dict[str, Any] = Field(default_factory=dict)


class JudgeRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_snapshot: str
    prompt_version: str
    decode: dict[str, Any] = Field(default_factory=dict)


class EvalEvidence(BaseModel):
    """对外证据：必须携带层级、复现层级与裁判链（§9.5）。"""

    model_config = ConfigDict(extra="forbid")
    level: Literal["L1", "L2", "L3"]
    rubric_version: str
    metrics: dict[str, dict[str, Any]] = Field(default_factory=dict)
    reproduction_tier: Literal["T1", "T2", "T3"]
    model_snapshot: str
    decode: dict[str, Any] = Field(default_factory=dict)
    renderer_version: str
    baseline_id: str | None = None
    label: Literal["optimizing", "compatible", "rejected"] | None = None
    judge: JudgeRef | None = None
    reviewer_pool_id: str | None = None
    expires_at: str | None = None
