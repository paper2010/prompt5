"""EvalCase：评测单元 = 任务 × 模型快照 × seed × repeat。

契约（执行方案 §9.1）：提示词变体是「处理因素」，在同一 case 内配对；
聚合顺序固定为 case → 任务 → 跨任务检验，禁止跳层或把 repeats 当独立样本。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from ...canonical import tuple_hash

__all__ = ["EvalCase", "EvalRow", "aggregate_to_tasks"]


@dataclass(frozen=True)
class EvalCase:
    task_id: str
    model_snapshot: str
    seed: int
    repeat_idx: int

    @property
    def case_id(self) -> str:
        return tuple_hash(
            [
                ("task", self.task_id),
                ("model", self.model_snapshot),
                ("seed", str(self.seed)),
                ("repeat", str(self.repeat_idx)),
            ]
        )


@dataclass(frozen=True)
class EvalRow:
    case: EvalCase
    variant: str
    passed: bool
    score: float
    output: str = ""
    detail: str = ""


def aggregate_to_tasks(rows: Iterable[EvalRow]) -> dict[str, dict[str, dict[str, float]]]:
    """case 级结果 → 任务级聚合：{task_id: {variant: {"pass_rate","mean_score"}}}。"""
    buckets: dict[str, dict[str, list[EvalRow]]] = {}
    for row in rows:
        buckets.setdefault(row.case.task_id, {}).setdefault(row.variant, []).append(row)

    result: dict[str, dict[str, dict[str, float]]] = {}
    for task_id, variants in buckets.items():
        result[task_id] = {}
        for variant, items in variants.items():
            count = len(items)
            result[task_id][variant] = {
                "pass_rate": sum(1 for item in items if item.passed) / count,
                "mean_score": sum(item.score for item in items) / count,
                "cases": float(count),
            }
    return result


def variants_of(summary: dict[str, dict[str, dict[str, float]]]) -> Sequence[str]:
    names: set[str] = set()
    for variants in summary.values():
        names.update(variants)
    return sorted(names)
