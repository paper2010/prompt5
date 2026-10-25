"""种子反解：把既有提示词（渲染形态）逆向解析为 IR v3。

边界（诚实说明）：只保证对本项目渲染器（m3_cards，template tpl1）的输出可往返；
外部任意格式的提示词只做「尽量识别 + 记 assumption」，识别不到结构时退化为
「整段文本作为 goal.outcome」，不猜测隐藏槽位。
"""

from __future__ import annotations

import re
from typing import Any

from ..ids import new_ir_id, new_patch_id
from ..ir import IR, build_ir

__all__ = ["parse_seed_prompt", "split_sections"]

_SECTION_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_NUMBERED_RE = re.compile(r"^\s*\d+\.\s+(.*)$", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*-\s+(.*)$", re.MULTILINE)


def split_sections(text: str) -> dict[str, str]:
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return {}
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1).strip()] = text[start:end].strip()
    return sections


def _numbered(body: str) -> list[str]:
    return [match.group(1).strip() for match in _NUMBERED_RE.finditer(body)]


def _bullets(body: str) -> list[str]:
    return [match.group(1).strip() for match in _BULLET_RE.finditer(body)]


def _split_labeled(body: str, labels: list[str]) -> dict[str, str]:
    """按「必须：」「禁止：」等标签切段。"""
    positions: list[tuple[int, str]] = []
    for label in labels:
        index = body.find(label + "：")
        if index >= 0:
            positions.append((index, label))
    positions.sort()
    result: dict[str, str] = {label: "" for label in labels}
    for order, (index, label) in enumerate(positions):
        start = index + len(label) + 1
        end = positions[order + 1][0] if order + 1 < len(positions) else len(body)
        result[label] = body[start:end].strip()
    return result


def _strip_prefix(text: str, prefix: str) -> str:
    text = text.strip()
    return text[len(prefix) :].strip() if text.startswith(prefix) else text


def parse_seed_prompt(
    text: str,
    *,
    ir_id: str | None = None,
    lineage_id: str | None = None,
    source_tag: str = "seed_parse",
) -> IR:
    """解析既有提示词；返回带 checksum 的 IR（version=1）。"""
    sections = split_sections(text)
    assumptions: list[str] = []

    if not sections:
        # 无结构：整段作为目标，明确记录降级
        assumptions.append("提示词不含 Markdown 分组标题，整段作为 goal.outcome 处理")
        sections = {"目标": text.strip()}

    slots: dict[str, Any] = {}

    role = _strip_prefix(sections.get("角色", ""), "你是").rstrip("。").strip()
    if role:
        slots["role"] = role

    goal_body = sections.get("目标", "")
    outcome = goal_body
    done: list[str] = []
    non_goals: list[str] = []
    if "完成标准：" in goal_body:
        head, tail = goal_body.split("完成标准：", 1)
        outcome = head.strip()
        if "明确不做：" in tail:
            tail, rest = tail.split("明确不做：", 1)
            non_goals = _bullets(rest)
        done = _bullets(tail)
    elif "明确不做：" in goal_body:
        head, rest = goal_body.split("明确不做：", 1)
        outcome = head.strip()
        non_goals = _bullets(rest)
    slots["goal"] = {
        "outcome": outcome.strip(),
        "done_criteria": done,
        "non_goals": non_goals,
    }

    constraints_body = sections.get("约束", "")
    labeled = _split_labeled(constraints_body, ["必须", "禁止", "风格"])
    slots["constraints"] = {
        "must": _numbered(labeled["必须"]) or _bullets(labeled["必须"]),
        "must_not": _bullets(labeled["禁止"]),
        "style": _bullets(labeled["风格"]),
    }

    slots["workflow"] = _numbered(sections.get("工作流", ""))
    slots["feedback_protocol"] = {}
    feedback = _strip_prefix(sections.get("失败反馈", ""), "若无法完成，按以下格式报告：")
    if feedback:
        slots["feedback_protocol"] = {"on_fail_report": feedback}

    output_body = sections.get("输出格式", "")
    output: dict[str, Any] = {"format": "文本", "schema": None, "length_budget": ""}
    for line in output_body.splitlines():
        line = line.strip()
        if line.startswith("格式："):
            output["format"] = _strip_prefix(line, "格式：")
        elif line.startswith("长度："):
            output["length_budget"] = _strip_prefix(line, "长度：")
    slots["output"] = output

    examples: list[dict[str, str]] = []
    for block in sections.get("示例", "").split("\n\n"):
        if "输入：" in block and "期望输出：" in block:
            head, tail = block.split("期望输出：", 1)
            examples.append({"input": _strip_prefix(head, "输入："), "expected": tail.strip()})
    slots["examples"] = examples
    slots["inputs"] = []

    freeform: list[dict[str, Any]] = []
    for title, body in sections.items():
        if title.startswith("补充："):
            freeform.append({"text": body.strip(), "note": title[len("补充：") :].strip()})
    if sections and not slots["goal"]["outcome"]:
        assumptions.append("未能从「目标」段解析出 outcome，已回退为空并用完成标准兜底")

    payload: dict[str, Any] = {
        "ir_id": ir_id or new_ir_id(),
        "version": 1,
        "lineage_id": lineage_id or f"lin-{new_patch_id()[:16].lower()}",
        "created": {
            "by": source_tag,
            "strategy_id": source_tag,
            "at": "parsed",
            "operator": "cli",
            "assumptions": assumptions,
        },
        "slots": slots,
        "freeform_extras": freeform,
        "provenance_map": {path: {"source": "seed"} for path in ("slots.role", "slots.goal.outcome")},
        "protect_registry": [],
    }
    return build_ir(payload)
