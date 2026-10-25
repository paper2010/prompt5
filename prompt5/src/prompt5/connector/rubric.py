"""任务级 Rubric 草案：与创建/确认流程共用同一版本化数据源。"""

from __future__ import annotations

from typing import Any, Sequence

from ..canonical import sha256_hex
from ..modules.m1_extractor import extract_rules

__all__ = ["build_rubric_draft"]


def build_rubric_draft(text: str, materials: Sequence[dict[str, Any]] = ()) -> dict[str, Any]:
    """从任务草稿生成只读验收要点；是否确认仍完全由用户显式操作决定。"""
    frame = extract_rules(text, materials=materials)
    slots = frame.slots
    goal = slots.get("goal") or {}
    constraints = slots.get("constraints") or {}
    output = slots.get("output") or {}
    candidates = [
        *(str(item) for item in goal.get("done_criteria") or []),
        *(str(item) for item in constraints.get("must") or []),
        *(str(item) for item in constraints.get("must_not") or []),
        f"输出格式符合：{output.get('format') or '文本'}",
    ]
    criteria = list(dict.fromkeys(item.strip() for item in candidates if item.strip()))
    version = sha256_hex(
        {
            "text": text.strip(),
            "materials": list(materials),
            "rubric_policy": "draft_then_confirm",
            "rubric_schema": "1",
        }
    )[:16]
    return {
        "version": f"rubric-{version}",
        "criteria": criteria,
        "source": "backend",
        "note": "由服务端从任务草稿生成，用于本次人工确认；V1 为只读草案。",
    }
