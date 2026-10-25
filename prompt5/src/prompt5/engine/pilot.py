"""M3 pilot：候选（骨架冠军 vs B2 朴素基线）在机器判定任务上的评测。

执行器可切换：
- `ScriptedExecutor`（默认）：离线模拟，仅验证链路，报告会标注「不构成效果证据」；
- `OpenAICompatExecutor`（live）：真实调用配置中的目标模型（L3 端点由用户填写）。
可选启用 L2：用裁判池里「与被测族、生成器族都不同族」的裁判做交换双裁。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..modules.m1_extractor import extract_rules
from ..modules.m3_cards import render
from ..modules.m4_generator import generate_from_frame
from ..modules.m5_eval.l2_judge import PairwiseJudge, judge_pair
from ..modules.m5_eval.l3_exec import Executor, ScriptedExecutor
from ..modules.m5_eval.runner import Candidate, EvalReport, compare, evaluate, load_tasks, to_markdown

__all__ = ["build_candidates", "run_pilot", "l2_summary"]


def build_candidates(model_id: str) -> list[Candidate]:
    def champion(task: dict[str, Any]) -> str:
        frame = extract_rules(str(task["prompt_brief"]))
        return render(generate_from_frame(frame), model_id).text

    def b2(task: dict[str, Any]) -> str:
        return f"请完成以下任务：{task['prompt_brief']}"

    return [Candidate("champion", champion), Candidate("b2", b2)]


def l2_summary(
    tasks: list[dict[str, Any]],
    candidates: list[Candidate],
    judge: PairwiseJudge,
    *,
    judge_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """逐任务做 champion vs b2 的交换双裁，统计胜负平与不一致次数。"""
    champion, b2 = candidates[0], candidates[1]
    result: dict[str, Any] = {
        "judge": (judge_meta or {}).get("model", "unknown"),
        "tasks": 0,
        "a_wins": 0,
        "b_wins": 0,
        "ties": 0,
        "inconsistent": 0,
    }
    for task in tasks:
        rubric = list(task.get("done_criteria") or ["输出满足任务要求", "格式可直接使用"])
        judgement = judge_pair(judge, champion.prompt_for(task), b2.prompt_for(task), rubric)
        result["tasks"] += 1
        if judgement.winner == "a":
            result["a_wins"] += 1
        elif judgement.winner == "b":
            result["b_wins"] += 1
        else:
            result["ties"] += 1
        if not judgement.consistent:
            result["inconsistent"] += 1
    return result


def run_pilot(
    tasks_path: str | Path = "benchmarks/tasks.jsonl",
    out_path: str | Path = "reports/m3-pilot.md",
    *,
    repeats: int = 3,
    margin: float = 0.1,
    model_id: str = "deepseek",
    executor: Executor | None = None,
    judge: PairwiseJudge | None = None,
    judge_meta: dict[str, Any] | None = None,
    bench_version: str = "pilot-v1",
) -> tuple[EvalReport, dict[str, Any], str]:
    tasks = load_tasks(tasks_path)
    candidates = build_candidates(model_id)
    active_executor = executor or ScriptedExecutor()

    report = evaluate(
        candidates,
        tasks,
        active_executor,
        model_snapshot=f"{model_id}@{active_executor.name}",
        repeats=repeats,
        bench_version=bench_version,
    )
    comparison = compare(report, "champion", "b2", margin=margin)
    markdown = to_markdown(report, comparison)

    if judge is not None:
        summary = l2_summary(tasks, candidates, judge, judge_meta=judge_meta)
        lines = [
            "",
            "## L2 表达评估（交换双裁）",
            "",
            f"- 裁判：`{summary['judge']}`（回避规则：≠被测族、≠生成器族）",
            f"- 覆盖任务：{summary['tasks']}　champion 胜 {summary['a_wins']}　b2 胜 {summary['b_wins']}　"
            f"平 {summary['ties']}　双裁不一致 {summary['inconsistent']}",
            "- 说明：L2 只反映「表达质量」的相对序，不构成效果证据。",
            "",
        ]
        markdown = markdown + "\n".join(lines)

    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    return report, comparison, markdown
