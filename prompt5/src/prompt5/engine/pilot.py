"""M3 pilot：候选（骨架冠军 vs B2 朴素基线）在 5 个机器判定任务上的离线评测。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..modules.m1_extractor import extract_rules
from ..modules.m3_cards import render
from ..modules.m4_generator import generate_from_frame
from ..modules.m5_eval.l3_exec import ScriptedExecutor
from ..modules.m5_eval.runner import Candidate, EvalReport, compare, evaluate, load_tasks, to_markdown

__all__ = ["champion_builder", "b2_builder", "run_pilot"]


def champion_builder(task: dict[str, Any]) -> str:
    frame = extract_rules(str(task["prompt_brief"]))
    ir = generate_from_frame(frame)
    return render(ir, "glm5").text


def b2_builder(task: dict[str, Any]) -> str:
    """B2 = 单策略自动基线（朴素直出，无结构、无约束、无验收）。"""
    return f"请完成以下任务：{task['prompt_brief']}"


def run_pilot(
    tasks_path: str | Path = "benchmarks/tasks.jsonl",
    out_path: str | Path = "reports/m3-pilot.md",
    *,
    repeats: int = 3,
    margin: float = 0.1,
) -> tuple[EvalReport, dict[str, Any], str]:
    tasks = load_tasks(tasks_path)
    candidates = [Candidate("champion", champion_builder), Candidate("b2", b2_builder)]
    report = evaluate(
        candidates,
        tasks,
        ScriptedExecutor(),
        model_snapshot="glm5@mock",
        repeats=repeats,
        bench_version="pilot-v1",
    )
    comparison = compare(report, "champion", "b2", margin=margin)
    markdown = to_markdown(report, comparison)
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    return report, comparison, markdown
