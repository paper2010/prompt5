"""渲染管线：基线 IR ⊕ 模型 Overlay → 逐模型渲染；含 stale 判定与显式重基。

契约（执行方案 §4.2/§6.3）：
- Overlay 补丁的 base.checksum 必须等于当前 IR 的 checksum，否则判 stale（排除出渲染并告警）；
- 重基 = 以当前 IR 为新 base 重新生成同语义补丁（显式动作，不允许静默套用）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..applier import ApplyError, apply as apply_pure
from ..ids import new_patch_id
from ..ir import IR
from ..modules.m3_cards import RenderResult, render
from ..patch import Patch

__all__ = ["OverlayResult", "apply_overlays", "render_with_overlays", "rebase_patch"]


@dataclass
class OverlayResult:
    ir: IR
    applied: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)


def apply_overlays(base_ir: IR, overlays: list[Patch]) -> OverlayResult:
    current = base_ir
    applied: list[str] = []
    stale: list[str] = []
    for patch in overlays:
        if patch.base.checksum != current.checksum:
            stale.append(patch.patch_id)
            continue
        result = apply_pure(current, patch)
        current = result.ir
        applied.append(patch.patch_id)
    return OverlayResult(ir=current, applied=applied, stale=stale)


def render_with_overlays(
    base_ir: IR, model_id: str, overlays: list[Patch] | None = None
) -> RenderResult:
    outcome = apply_overlays(base_ir, list(overlays or []))
    return render(
        outcome.ir,
        model_id,
        overlays=outcome.applied,
        stale_overlays=outcome.stale,
    )


def rebase_patch(patch: Patch, new_ir: IR, *, reason: str = "overlay rebase") -> Patch:
    """把 Overlay 补丁重基到当前 IR；语义不变，base 与 patch_id 更新。

    若原 ops 在新的 base 上无法执行（loc 失效/保护冲突），抛 ApplyError —— 调用方
    必须显式处理，不允许「尽量应用」。
    """
    body = patch.model_dump(mode="json", by_alias=True)
    body.pop("patch_hash", None)
    body["patch_id"] = new_patch_id()
    body["base"] = {"ir_id": new_ir.ir_id, "version": new_ir.version, "checksum": new_ir.checksum}
    body["idempotency_key"] = f"{patch.idempotency_key}-rebase"
    body.setdefault("created", {})
    body["created"] = {**body["created"], "reason": reason}
    rebased = Patch.model_validate(body).model_copy(update={"patch_hash": ""})
    rebased = rebased.model_copy(update={"patch_hash": rebased.compute_hash()})
    apply_pure(new_ir, rebased)  # 校验可执行性，失败即抛 ApplyError
    return rebased
