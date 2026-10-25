"""M4 生成引擎（M2 范围：骨架策略单策略）。

骨架策略 = 以 IntentFrame 为输入、按任务类型套用结构化骨架产出 IR v3。
策略 ID 写入 created.strategy_id，供后续归因。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..ids import new_ir_id, new_patch_id
from ..ir import IR, build_ir
from .m1_extractor import IntentFrame

__all__ = ["STRATEGY_ID", "ROLE_BY_TYPE", "generate_from_frame"]

STRATEGY_ID = "skeleton"

ROLE_BY_TYPE = {
    "analysis": "资深数据分析师",
    "transform": "数据整理工程师",
    "draft": "资深内容编辑",
    "extraction": "信息抽取专员",
    "code": "高级软件工程师",
    "other": "通用任务执行者",
}

_DEFAULT_FEEDBACK = {"on_fail_report": "现象|复现|已尝试|影响面"}


def generate_from_frame(
    frame: IntentFrame,
    *,
    ir_id: str | None = None,
    lineage_id: str | None = None,
    created_by: str = "generator",
) -> IR:
    slots = deepcopy(frame.slots)
    goal = slots.setdefault("goal", {})
    output = slots.setdefault("output", {})
    constraints = slots.setdefault("constraints", {})
    constraints.setdefault("must", [])
    constraints.setdefault("must_not", [])
    constraints.setdefault("style", [])

    goal.setdefault("outcome", "")
    goal.setdefault("done_criteria", [])
    goal.setdefault("non_goals", [])
    if not goal["done_criteria"]:
        goal["done_criteria"] = ["覆盖目标要求的全部要素"]
    output.setdefault("format", "文本")
    output.setdefault("schema", None)
    output.setdefault("length_budget", "")
    if not constraints["must"]:
        constraints["must"] = [f"输出符合格式要求：{output['format']}"]

    slots.setdefault("role", ROLE_BY_TYPE.get(frame.task_type, ROLE_BY_TYPE["other"]))
    slots.setdefault("inputs", [])
    slots.setdefault("examples", [])
    slots.setdefault("workflow", ["解析目标", "执行任务", "按输出格式交付", "对照完成标准自检"])
    slots.setdefault("feedback_protocol", dict(_DEFAULT_FEEDBACK))
    if not slots["feedback_protocol"]:
        slots["feedback_protocol"] = dict(_DEFAULT_FEEDBACK)

    identifier = ir_id or new_ir_id()
    payload: dict[str, Any] = {
        "ir_id": identifier,
        "version": 1,
        "lineage_id": lineage_id or f"lin-{new_patch_id()[:16].lower()}",
        "created": {
            "by": created_by,
            "strategy_id": STRATEGY_ID,
            "at": "generated",
            "operator": "cli",
            "assumptions": list(frame.assumptions),
            "missing": list(frame.missing),
        },
        "slots": slots,
        "freeform_extras": [],
        "provenance_map": {
            "slots.goal.outcome": {"source": "intent_frame"},
            "slots.output.format": {"source": "intent_frame"},
        },
        "protect_registry": [],
    }
    return build_ir(payload)
