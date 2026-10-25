"""流程 B（迭代）：种子反解 → 候选补丁 → 回归保护 → 台账应用。

规则（执行方案 §4/§9.4）：
- 每轮只产出一个候选补丁；应用前先在副本上模拟（零部分应用）；
- 有回归风险（父版本已通过的任务退步）→ 拒绝并记录，不写台账；
- 所有拒绝都要带可解释原因（apply_failed / regression / no_change）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from ..applier import ApplyError, apply as apply_pure
from ..ids import new_patch_id
from ..ir import IR
from ..modules.m1_seed import parse_seed_prompt
from ..modules.m3_cards import render
from ..modules.m5_eval.l3_exec import Executor, ScriptedExecutor
from ..modules.m5_eval.regression import check_prompt_regression
from ..patch import Patch
from .render_pipeline import apply_overlays

__all__ = [
    "IterateOutcome",
    "propose_patch",
    "run_iterate",
    "iterate_from_text",
    "select_regression_tasks",
]

_FORMAT_HINTS = (
    ("表格", "结构化表格"),
    ("报告", "分析报告（结论、要点、数据依据）"),
    ("清单", "结构化清单"),
    ("代码", "可运行代码 + 说明"),
)


def _base_patch(ir: IR, ops: list[dict[str, Any]], intent: str) -> Patch:
    patch_id = new_patch_id()
    body = {
        "schema_version": "3",
        "patch_id": patch_id,
        "base": {"ir_id": ir.ir_id, "version": ir.version, "checksum": ir.checksum},
        "model_scope": None,
        "intent": intent,
        "ops": ops,
        "idempotency_key": f"iter-{patch_id[:12].lower()}",
        "created": {"by": "iter", "at": "generated", "operator": "cli"},
    }
    patch = Patch.model_validate(body)
    return patch.model_copy(update={"patch_hash": patch.compute_hash()})


def propose_patch(ir: IR, task_text: str) -> Patch | None:
    """规则驱动的单补丁提案；无可改进点时返回 None（不制造 no-op）。"""
    task = (task_text or "").strip()

    # 1) 输出格式对齐
    for keyword, target_format in _FORMAT_HINTS:
        if keyword in task and keyword not in ir.slots.output.format:
            return _base_patch(
                ir,
                [
                    {
                        "op": "REWRITE",
                        "loc": "slots.output.format",
                        "content": target_format,
                        "reason": f"用户要求 {keyword}，对齐输出格式",
                    }
                ],
                "improve",
            )

    # 2) 追加「必须」约束
    if "必须" in task:
        clause = task.split("必须", 1)[1].strip(" ：:，,。")
        if clause and clause not in ir.slots.constraints.must:
            return _base_patch(
                ir,
                [
                    {
                        "op": "ADD",
                        "loc": "slots.constraints.must",
                        "content": clause,
                        "reason": "用户显式提出的硬约束",
                    }
                ],
                "improve",
            )

    # 3) 追加「禁止」约束
    if any(word in task for word in ("不要", "禁止", "不得")):
        for word in ("不要", "禁止", "不得"):
            if word in task:
                clause = task.split(word, 1)[1].strip(" ：:，,。")
                if clause and clause not in ir.slots.constraints.must_not:
                    return _base_patch(
                        ir,
                        [
                            {
                                "op": "ADD",
                                "loc": "slots.constraints.must_not",
                                "content": clause,
                                "reason": "用户显式提出的禁止项",
                            }
                        ],
                        "improve",
                    )

    # 4) 缺完成标准 → 补齐
    if not ir.slots.goal.done_criteria:
        return _base_patch(
            ir,
            [
                {
                    "op": "ADD",
                    "loc": "slots.goal.done_criteria",
                    "content": "覆盖目标要求的全部要素",
                    "reason": "缺少验收标准，补最小可判定标准",
                }
            ],
            "improve",
        )

    # 5) 约束过多 → 精简（需证据引用）
    if len(ir.slots.constraints.must) >= 4:
        last_id = ir.item_ids["slots.constraints.must"][-1]
        return _base_patch(
            ir,
            [
                {
                    "op": "DELETE",
                    "loc": f"slots.constraints.must[{last_id}]",
                    "reason": "约束条目过多，候选精简项（待消融确认）",
                    "evidence_refs": ["ablation:pending"],
                }
            ],
            "simplify",
        )
    return None


def select_regression_tasks(tasks: Sequence[dict[str, Any]], seed_text: str) -> list[dict[str, Any]]:
    """挑选「种子版本已能通过」的任务做回归集（其余任务不构成回归基线）。"""
    selected = []
    for task in tasks:
        markers = (task.get("simulation") or {}).get("required_markers", [])
        if all(marker in seed_text for marker in markers):
            selected.append(task)
    return selected


@dataclass
class IterateOutcome:
    seed_ir: IR
    final_ir: IR
    applied: list[Patch] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    regression: dict[str, Any] = field(default_factory=dict)
    rounds: int = 0


def run_iterate(
    seed_ir: IR,
    task_text: str,
    ledger,
    *,
    model_id: str = "glm5",
    max_rounds: int = 2,
    regression_tasks: Sequence[dict[str, Any]] = (),
    executor: Executor | None = None,
) -> IterateOutcome:
    executor = executor or ScriptedExecutor()
    current = seed_ir
    applied: list[Patch] = []
    rejected: list[dict[str, Any]] = []
    regression_info: dict[str, Any] = {}

    for _ in range(max(0, max_rounds)):
        patch = propose_patch(current, task_text)
        if patch is None:
            break

        try:
            candidate = apply_pure(current, patch).ir
        except ApplyError as exc:
            rejected.append(
                {"patch_id": patch.patch_id, "reason": "apply_failed", "code": exc.code}
            )
            break

        if regression_tasks:
            check = check_prompt_regression(
                render(current, model_id).text,
                render(candidate, model_id).text,
                regression_tasks,
                executor,
            )
            regression_info = check.to_dict()
            if not check.passed:
                rejected.append(
                    {"patch_id": patch.patch_id, "reason": "regression", "detail": check.to_dict()}
                )
                break

        result = ledger.apply(patch)  # CAS：base 未变才落库
        current = result.ir
        applied.append(patch)

    return IterateOutcome(
        seed_ir=seed_ir,
        final_ir=current,
        applied=applied,
        rejected=rejected,
        regression=regression_info,
        rounds=len(applied),
    )


def iterate_from_text(
    seed_text: str,
    task_text: str,
    ledger,
    **kwargs: Any,
) -> IterateOutcome:
    seed_ir = parse_seed_prompt(seed_text)
    stored = ledger.create_ir(seed_ir.payload() | {"checksum": seed_ir.checksum})
    return run_iterate(stored, task_text, ledger, **kwargs)
