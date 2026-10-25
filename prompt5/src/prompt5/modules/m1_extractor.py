"""M1 意图解析：对话/任务文本 → IntentFrame（槽位 + 置信度 + 缺失清单）。

策略：规则抽取打底，LLM 结果覆盖（LLM 不可用或非法时保留规则结果并记 assumption）。
契约：执行方案 §3（M1 职责）、§11（硬约束：用户文本按不可信数据处理，只进结构字段）。
"""

from __future__ import annotations

import json
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..llm.client import LLMClient, LLMError, message

__all__ = ["IntentFrame", "extract_intent", "extract_rules", "EXTRACT_SYSTEM_PROMPT"]

TaskType = Literal["analysis", "transform", "draft", "extraction", "code", "other"]

EXTRACT_SYSTEM_PROMPT = (
    "你是意图解析器。只输出 JSON："
    '{"task_type": "...", "slots": {"goal": {"outcome": "..."}, "output": {"format": "..."}}, '
    '"confidence": {"<槽位路径>": 0-1}}。'
    "不得编造用户未提供的事实；不确定的槽位不要输出。"
)

REQUIRED_SLOTS = ("goal.outcome", "output.format", "constraints.must", "goal.done_criteria")


class IntentFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: TaskType = "other"
    slots: dict[str, Any] = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    source: Literal["llm", "rules", "merged"] = "rules"


_TASK_HINTS: list[tuple[tuple[str, ...], TaskType, str]] = [
    (("报告", "分析", "数据", "csv", "xlsx", "报表"), "analysis", "分析报告（结论、要点、数据依据）"),
    (("整理", "转换", "格式化", "合并", "拆分"), "transform", "结构化清单"),
    (("写", "文案", "邮件", "稿", "润色"), "draft", "成稿文本"),
    (("提取", "抽取", "识别字段"), "extraction", "结构化字段表"),
    (("代码", "脚本", "重构", "接口", "调试"), "code", "可运行代码 + 变更说明"),
]


def _detect(task: str) -> tuple[TaskType, str]:
    lowered = task.lower()
    for keywords, task_type, output_format in _TASK_HINTS:
        if any(keyword in task or keyword in lowered for keyword in keywords):
            return task_type, output_format
    return "other", "文本"


def extract_rules(task: str, *, materials: Sequence[dict[str, Any]] = ()) -> IntentFrame:
    """规则抽取（离线可用；也是 LLM 失败时的兜底）。"""
    task = task.strip()
    task_type, output_format = _detect(task)
    slots: dict[str, Any] = {
        "goal": {"outcome": task, "done_criteria": ["覆盖目标要求的全部要素", "可直接使用，无需二次排版"]},
        "output": {"format": output_format},
        "constraints": {"must": ["输出语言与用户输入一致"], "must_not": [], "style": []},
        "workflow": ["解析目标与材料", "执行任务", "按输出格式交付", "对照完成标准自检"],
        "feedback_protocol": {"on_fail_report": "现象|复现|已尝试|影响面"},
    }
    if task_type == "analysis":
        slots["constraints"]["must"].append("结论先行，数据与结论对应")
        slots["constraints"]["must_not"].append("不得编造未提供的数据")
    if task_type == "code":
        slots["constraints"]["must"].append("给出可运行命令与预期输出")

    assumptions: list[str] = []
    missing: list[str] = []

    if not materials and any(keyword in task for keyword in ("这份", "文件", "表格", "csv", "数据")):
        missing.append("inputs")
        assumptions.append("未提供材料引用（blob_id），按纯文本任务处理")
    if task_type == "other":
        missing.append("output.format")
        assumptions.append("未识别任务类型，输出格式按纯文本处理")

    return IntentFrame(
        task_type=task_type,
        slots=slots,
        confidence={"goal.outcome": 0.85, "output.format": 0.6 if task_type == "other" else 0.8},
        missing=missing,
        assumptions=assumptions,
        source="rules",
    )


def _recompute_missing(slots: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    goal = slots.get("goal") or {}
    output = slots.get("output") or {}
    constraints = slots.get("constraints") or {}
    if not goal.get("outcome"):
        missing.append("goal.outcome")
    if not output.get("format"):
        missing.append("output.format")
    if not constraints.get("must") and not constraints.get("must_not"):
        missing.append("constraints.must")
    if not goal.get("done_criteria"):
        missing.append("goal.done_criteria")
    return missing


def extract_intent(
    task: str,
    *,
    llm: LLMClient | None = None,
    materials: Sequence[dict[str, Any]] = (),
) -> IntentFrame:
    base = extract_rules(task, materials=materials)
    if llm is None:
        return base

    prompt = f"<<INTENT_EXTRACT>>\nTASK: {task}\nDIALOGUE_TURNS: 1"
    try:
        raw = llm.chat([message("system", EXTRACT_SYSTEM_PROMPT), message("user", prompt)])
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("intent payload must be an object")
        candidate = IntentFrame.model_validate(
            {
                **payload,
                "slots": payload.get("slots") or {},
                "confidence": payload.get("confidence") or {},
                "missing": [],
                "assumptions": [],
                "source": "llm",
            }
        )
    except (LLMError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        frame = base.model_copy(deep=True)
        frame.assumptions.append(f"LLM 抽取不可用（{type(exc).__name__}），已回退规则抽取")
        return frame

    merged_slots = _deep_merge(base.slots, candidate.slots)
    missing = _recompute_missing(merged_slots)
    for extra in base.missing:  # 规则阶段发现的缺失（如 inputs）不得被合并覆盖丢失
        if extra not in missing and not _slot_filled(merged_slots, extra):
            missing.append(extra)
    frame = IntentFrame(
        task_type=candidate.task_type if candidate.task_type != "other" else base.task_type,
        slots=merged_slots,
        confidence={**base.confidence, **candidate.confidence},
        missing=missing,
        assumptions=list(base.assumptions),
        source="merged",
    )
    return frame


def _slot_filled(slots: dict[str, Any], path: str) -> bool:
    if path == "inputs":
        return bool(slots.get("inputs"))
    node: Any = slots
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return bool(node)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(base))
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        elif value not in (None, "", [], {}):
            result[key] = value
    return result
