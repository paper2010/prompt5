"""流程 A（从零生成）最小闭环：任务文本 → IntentFrame → IR → 渲染 → L1。

M2 范围：单策略（骨架）、单模型卡（glm5）、Mock LLM 可全离线跑通。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..llm.client import LLMClient
from ..ir import IR
from ..modules.m1_extractor import IntentFrame, extract_intent
from ..modules.m3_cards import RenderResult, render
from ..modules.m4_generator import generate_from_frame
from ..modules.m5_eval.l1_rules import L1Report, check

__all__ = ["ZeroFlowResult", "run_zero"]


@dataclass
class ZeroFlowResult:
    frame: IntentFrame
    ir: IR
    rendered: RenderResult
    l1: L1Report

    @property
    def ok(self) -> bool:
        return self.l1.passed


def run_zero(
    task: str,
    *,
    llm: LLMClient | None = None,
    model_id: str = "glm5",
    ir_id: str | None = None,
    token_budget: int = 4000,
    materials: list[dict] | None = None,
) -> ZeroFlowResult:
    """执行从零生成链路；LLM 缺省时由调用方决定是否注入（None = 纯规则）。"""
    frame = extract_intent(task, llm=llm, materials=materials or ())
    ir = generate_from_frame(frame, ir_id=ir_id)
    rendered = render(ir, model_id)
    report = check(ir, rendered.text, token_budget=token_budget)
    return ZeroFlowResult(frame=frame, ir=ir, rendered=rendered, l1=report)
