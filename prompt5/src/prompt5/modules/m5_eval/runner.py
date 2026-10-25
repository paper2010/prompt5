"""评测流水线：候选 × 任务 × repeats → EvalCase → 任务聚合 → 统计对比 → 报告。

口径（执行方案 §9.1/§9.2）：
- 样本单位 = 任务；repeats 在任务内聚合后进入检验；
- 主端点 = 机器判定任务成功率；报告必须标注证据层级与执行器类型；
- 未检出差异只能表述为「未检出」，不得表述为「等效」。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from ...canonical import sha256_hex
from .cache import EvalCache
from .evalcase import EvalRow, aggregate_to_tasks
from .l3_exec import Executor, run_case
from .stats import bootstrap_ci, mcnemar_exact, tost_paired, wilcoxon_signed_rank

__all__ = [
    "Candidate",
    "EvalReport",
    "load_tasks",
    "evaluate",
    "compare",
    "to_markdown",
]


@dataclass
class Candidate:
    """候选 = 提示词构造器（每个任务各自生成提示词，符合「逐任务生成」语义）。"""

    name: str
    builder: Callable[[dict[str, Any]], str]
    variant_id: str = ""

    def prompt_for(self, task: dict[str, Any]) -> str:
        return self.builder(task)

    def prompt_hash_for(self, task: dict[str, Any]) -> str:
        return sha256_hex(self.prompt_for(task))


@dataclass
class EvalReport:
    candidates: list[Candidate]
    tasks: list[dict[str, Any]]
    rows: list[EvalRow]
    summary: dict[str, dict[str, dict[str, float]]]
    model_snapshot: str
    repeats: int
    executor_name: str
    bench_version: str
    cache_stats: dict[str, int] = field(default_factory=dict)

    @property
    def is_simulated(self) -> bool:
        return self.executor_name == "scripted"


def load_tasks(path: str | Path) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            task = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid task json at line {line_no}: {exc}") from exc
        for required in ("task_id", "prompt_brief", "machine_judge"):
            if required not in task:
                raise ValueError(f"task at line {line_no} missing {required!r}")
        tasks.append(task)
    if not tasks:
        raise ValueError(f"no tasks loaded from {path}")
    return tasks


def evaluate(
    candidates: Sequence[Candidate],
    tasks: Sequence[dict[str, Any]],
    executor: Executor,
    *,
    model_snapshot: str,
    repeats: int = 3,
    seeds: Sequence[int] = (1, 2, 3),
    bench_version: str = "pilot-v1",
    judge_id: str = "none",
    cache: EvalCache | None = None,
) -> EvalReport:
    if repeats != len(seeds):
        raise ValueError("repeats must equal len(seeds)")
    store = cache or EvalCache()
    rows: list[EvalRow] = []

    for task in tasks:
        for candidate in candidates:
            for repeat_idx, seed in enumerate(seeds):
                key = store.key(
                    prompt=candidate.prompt_hash_for(task),
                    model=model_snapshot,
                    task=str(task["task_id"]),
                    seed=str(seed),
                    repeat=str(repeat_idx),
                    bench=bench_version,
                    judge=judge_id,
                    executor=executor.name,
                )
                cached = store.get(key)
                if cached is not None:
                    rows.append(cached)
                    continue
                row = run_case(
                    executor,
                    task,
                    candidate.prompt_for(task),
                    variant=candidate.name,
                    model_snapshot=model_snapshot,
                    seed=seed,
                    repeat_idx=repeat_idx,
                )
                store.put(key, row)
                rows.append(row)

    return EvalReport(
        candidates=list(candidates),
        tasks=list(tasks),
        rows=rows,
        summary=aggregate_to_tasks(rows),
        model_snapshot=model_snapshot,
        repeats=repeats,
        executor_name=executor.name,
        bench_version=bench_version,
        cache_stats=store.stats(),
    )


def compare(
    report: EvalReport, first: str, second: str, *, margin: float = 0.1
) -> dict[str, Any]:
    """任务层配对对比：b/c、McNemar、Wilcoxon、均值差 bootstrap CI、TOST。"""
    tasks = sorted(report.summary)
    a_rates = [report.summary[task].get(first, {}).get("pass_rate", 0.0) for task in tasks]
    b_rates = [report.summary[task].get(second, {}).get("pass_rate", 0.0) for task in tasks]
    diffs = [a - b for a, b in zip(a_rates, b_rates)]

    a_only = sum(1 for a, b in zip(a_rates, b_rates) if a >= 0.5 > b)
    b_only = sum(1 for a, b in zip(a_rates, b_rates) if b >= 0.5 > a)

    point, low, high = bootstrap_ci(diffs)
    wilcoxon = wilcoxon_signed_rank(a_rates, b_rates)
    mcnemar = mcnemar_exact(a_only, b_only)

    return {
        "first": first,
        "second": second,
        "tasks": tasks,
        "rates_first": a_rates,
        "rates_second": b_rates,
        "diffs": diffs,
        "mean_diff": point,
        "ci_low": low,
        "ci_high": high,
        "mcnemar": {"b": a_only, "c": b_only, "p_value": mcnemar.p_value},
        "wilcoxon": {"statistic": wilcoxon.statistic, "p_value": wilcoxon.p_value, "method": wilcoxon.method},
        "tost": tost_paired(diffs, margin=margin),
        "n_tasks": len(tasks),
    }


def to_markdown(report: EvalReport, comparison: dict[str, Any]) -> str:
    label = (
        "⚠️ 模拟执行器（scripted）：仅验证评测链路，**不构成效果证据**"
        if report.is_simulated
        else f"执行器：{report.executor_name}"
    )
    lines: list[str] = [
        "# M3 Pilot 评测报告",
        "",
        f"- 证据标签：{label}",
        f"- 基准版本：`{report.bench_version}`　模型快照：`{report.model_snapshot}`　重复：{report.repeats}",
        f"- 样本单位：任务（n={comparison['n_tasks']}）；repeats 已在任务内聚合",
        f"- 缓存：{report.cache_stats}",
        "",
        "## 逐任务通过率",
        "",
        f"| 任务 | {comparison['first']} | {comparison['second']} | 差值 |",
        "|---|---|---|---|",
    ]
    for task, a, b, diff in zip(
        comparison["tasks"], comparison["rates_first"], comparison["rates_second"], comparison["diffs"]
    ):
        lines.append(f"| {task} | {a:.2f} | {b:.2f} | {diff:+.2f} |")

    mcnemar = comparison["mcnemar"]
    wilcoxon = comparison["wilcoxon"]
    tost = comparison["tost"]
    lines += [
        "",
        "## 统计结果",
        "",
        f"- 均值差：{comparison['mean_diff']:+.3f}，bootstrap 95% CI [{comparison['ci_low']:+.3f}, {comparison['ci_high']:+.3f}]",
        f"- McNemar（任务层二分）：b={mcnemar['b']} c={mcnemar['c']}，精确双侧 p={mcnemar['p_value']:.4f}",
        f"- Wilcoxon 符号秩（{wilcoxon['method']}）：W={wilcoxon['statistic']:.1f}，p={wilcoxon['p_value']:.4f}",
        f"- TOST 等效判定（margin={tost['margin']}）：90% CI [{tost['ci_low']:+.3f}, {tost['ci_high']:+.3f}] → "
        f"{'等效' if tost['equivalent'] else '未达等效'}",
        "",
        "## 结论（按声明纪律表述）",
        "",
    ]
    if mcnemar["p_value"] < 0.05 and comparison["ci_low"] > 0:
        lines.append("- 在该基准上检出差异（p<0.05 且 CI 下限>0）；仍需确认样本量与功效是否满足预注册要求。")
    elif comparison["ci_low"] > 0:
        lines.append(
            "- **方向一致但功效不足**：bootstrap CI 不含 0，而配对检验未达显著（n=5）。"
            "按预注册口径不得宣称有效，必须扩大基准后重跑。"
        )
    elif comparison["ci_low"] <= 0 <= comparison["ci_high"]:
        lines.append(
            "- **未检出显著差异**（CI 跨 0）。不得表述为「等效」，也不得外推为系统有效性结论。"
        )
    else:
        lines.append("- 检出负向信号：需核查候选缺陷与基线构造，禁止事后挑选指标重述结论。")
    lines += [
        "",
        "> 说明：本报告由 M3 pilot 生成，执行器为离线模拟；真实结论必须在目标模型上以 L3 实测并预注册后产生。",
        "",
    ]
    return "\n".join(lines)
