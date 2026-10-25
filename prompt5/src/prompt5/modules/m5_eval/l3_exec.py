"""L3 执行验证：目标模型执行 + 机器判定。

说明（诚实边界）：
- 本模块只负责「执行 → 判定」管线；`ScriptedExecutor` 是**离线模拟器**，其行为由
  benchmark 任务的 `simulation` 字段驱动，仅用于验证评测链路，**不构成效果证据**。
- 真机执行由 `OpenAICompatExecutor`（M3 后半段，需端点）提供，接口一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...llm.client import LLMClient
from .evalcase import EvalCase, EvalRow

__all__ = [
    "MachineVerdict",
    "judge_machine",
    "Executor",
    "ScriptedExecutor",
    "OpenAICompatExecutor",
    "run_case",
]


@dataclass
class MachineVerdict:
    passed: bool
    detail: str = ""


def judge_machine(output: str, spec: dict[str, Any]) -> MachineVerdict:
    """机器判定：exact_match / contains / checklist / numeric。"""
    kind = spec.get("kind")
    text = output or ""

    if kind == "exact_match":
        expected = str(spec.get("expected", ""))
        normalized = text.strip()
        passed = normalized == expected
        return MachineVerdict(passed, "exact match" if passed else f"expected {expected!r}")

    if kind in {"contains", "checklist"}:
        required = [str(item) for item in spec.get("all", spec.get("items", []))]
        missing = [item for item in required if item not in text]
        return MachineVerdict(not missing, "all present" if not missing else f"missing {missing}")

    if kind == "numeric":
        expected = float(spec.get("expected", 0))
        tolerance = float(spec.get("tolerance", 0.0))
        import re

        numbers = [float(match) for match in re.findall(r"-?\d+(?:\.\d+)?", text)]
        hit = any(abs(value - expected) <= tolerance for value in numbers)
        return MachineVerdict(hit, f"expected ≈{expected}±{tolerance}, found {numbers[:5]}")

    return MachineVerdict(False, f"unknown judge kind {kind!r}")


class Executor(Protocol):
    name: str

    def execute(self, prompt: str, task: dict[str, Any]) -> str: ...


class ScriptedExecutor:
    """离线模拟执行器（仅链路验证）：提示词命中 required_markers 才返回 gold。

    benchmark 任务形如：
      "simulation": {"required_markers": ["输出格式"], "gold": "...", "degraded": "..."}
    """

    name = "scripted"

    def execute(self, prompt: str, task: dict[str, Any]) -> str:
        simulation = task.get("simulation") or {}
        markers = [str(marker) for marker in simulation.get("required_markers", [])]
        if all(marker in prompt for marker in markers):
            return str(simulation.get("gold", ""))
        return str(simulation.get("degraded", ""))


def run_case(
    executor: Executor,
    task: dict[str, Any],
    prompt: str,
    *,
    variant: str,
    model_snapshot: str,
    seed: int,
    repeat_idx: int,
) -> EvalRow:
    case = EvalCase(
        task_id=str(task["task_id"]),
        model_snapshot=model_snapshot,
        seed=seed,
        repeat_idx=repeat_idx,
    )
    output = executor.execute(prompt, task)
    verdict = judge_machine(output, task.get("machine_judge") or {})
    return EvalRow(
        case=case,
        variant=variant,
        passed=verdict.passed,
        score=1.0 if verdict.passed else 0.0,
        output=output,
        detail=verdict.detail,
    )


class OpenAICompatExecutor:
    """L3 真实执行器：把提示词发给目标模型，取其输出交机器判定。

    端点/密钥来自配置（targets 段），temperature 固定 0 以保证可复现性优先。
    """

    def __init__(self, client: LLMClient, *, name: str | None = None) -> None:
        self.client = client
        self.name = name or f"live:{getattr(client, 'name', 'model')}"

    def execute(self, prompt: str, task: dict[str, Any]) -> str:
        budget = int((task.get("model_budget") or {}).get("max_tokens", 1024))
        return self.client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=budget,
        )
