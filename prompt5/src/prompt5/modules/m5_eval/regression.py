"""回归保护：候选提示词不得在父版本已通过的任务上退步。

口径（执行方案 §9.4）：回归判定在「同任务、同模型」下逐任务比较通过率，
只有候选严格低于基线（超出 epsilon）才记回归；被拦下的补丁不得写入台账。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .l3_exec import Executor, run_case

__all__ = ["RegressionResult", "check_prompt_regression"]


@dataclass
class RegressionResult:
    passed: bool
    before: dict[str, float] = field(default_factory=dict)
    after: dict[str, float] = field(default_factory=dict)
    regressions: list[dict[str, Any]] = field(default_factory=list)
    tasks_checked: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "tasks_checked": self.tasks_checked,
            "before": self.before,
            "after": self.after,
            "regressions": self.regressions,
        }


def check_prompt_regression(
    before_text: str,
    after_text: str,
    tasks: Sequence[dict[str, Any]],
    executor: Executor,
    *,
    model_snapshot: str = "glm5@mock",
    epsilon: float = 0.0,
) -> RegressionResult:
    before: dict[str, float] = {}
    after: dict[str, float] = {}
    regressions: list[dict[str, Any]] = []

    for task in tasks:
        task_id = str(task["task_id"])
        row_before = run_case(
            executor, task, before_text, variant="before", model_snapshot=model_snapshot, seed=1, repeat_idx=0
        )
        row_after = run_case(
            executor, task, after_text, variant="after", model_snapshot=model_snapshot, seed=1, repeat_idx=0
        )
        before[task_id] = 1.0 if row_before.passed else 0.0
        after[task_id] = 1.0 if row_after.passed else 0.0
        if after[task_id] < before[task_id] - epsilon:
            regressions.append(
                {
                    "task_id": task_id,
                    "before": before[task_id],
                    "after": after[task_id],
                    "detail": row_after.detail,
                }
            )

    return RegressionResult(
        passed=not regressions,
        before=before,
        after=after,
        regressions=regressions,
        tasks_checked=len(tasks),
    )
