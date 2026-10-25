"""M7 基准骨架：30 任务（10 校准 / 20 确证）+ 隐藏集 + B1-OSS 基线 + 预注册 + 门禁判定。

人工预算替代（已确认）：B1 由「开源专家提示词模板」构成（B1-OSS），并在预注册中显式声明
`human_blind_eval=false`。结论只能表述为「相对开源专家模板基线的机器可判定任务成功率」，
不得表述为「超过人工专家」或「全面最佳」。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..modules.m1_extractor import extract_rules
from ..modules.m3_cards import render
from ..modules.m4_generator import generate_from_frame
from ..modules.m5_eval.runner import Candidate, EvalReport, compare, evaluate, load_tasks

__all__ = [
    "BASELINE_ID",
    "BASELINE_TIER",
    "B1_SOURCES",
    "B1_TEMPLATES",
    "b1_oss_builder",
    "build_candidates",
    "load_bench",
    "validate_bench",
    "build_prereg",
    "save_prereg",
    "load_prereg",
    "gate_for_model",
    "render_gate_markdown",
]

BASELINE_ID = "b1-oss"
BASELINE_TIER = "oss-expert-template"

# 许可已核实：CC0-1.0（提示词内容）/ Apache-2.0（工具与模板集）
B1_SOURCES = [
    {
        "id": "f/prompts.chat",
        "url": "https://github.com/f/prompts.chat",
        "license": "CC0-1.0",
        "usage": "act-as 角色模板范式参考，改写为中文任务模板",
    },
    {
        "id": "bigscience-workshop/promptsource",
        "url": "https://github.com/bigscience-workshop/promptsource",
        "license": "Apache-2.0",
        "usage": "input/target 分离与模板化思路参考",
    },
]

B1_TEMPLATES: dict[str, str] = {
    "analysis": "你是一位资深数据分析师。\n任务：{brief}\n请先给出结论，再列出支撑要点与数据依据。\n输出：结论 + 要点 + 依据。",
    "extraction": "你是信息抽取助手。\n任务：{brief}\n只输出结果本身，不要解释。",
    "transform": "你是数据整理助手。\n任务：{brief}\n按字段逐项输出，使用「字段：值」的形式。",
    "draft": "你是内容编辑。\n任务：{brief}\n语言自然、信息密度高，避免空话。",
    "code": "你是高级工程师。\n任务：{brief}\n给出可运行代码与运行命令，再简述关键实现。",
}


def b1_oss_builder(task: dict[str, Any]) -> str:
    ttype = str(task.get("type", "other"))
    template = B1_TEMPLATES.get(ttype) or B1_TEMPLATES["analysis"]
    return template.format(brief=task["prompt_brief"])


def _champion_builder(model_id: str):
    def build(task: dict[str, Any]) -> str:
        frame = extract_rules(str(task["prompt_brief"]))
        return render(generate_from_frame(frame), model_id).text

    return build


def build_candidates(model_id: str) -> list[Candidate]:
    return [
        Candidate("champion", _champion_builder(model_id)),
        Candidate(BASELINE_ID, b1_oss_builder),
    ]


def load_bench(path: str | Path) -> list[dict[str, Any]]:
    return load_tasks(path)


def validate_bench(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(tasks)
    calibration = sum(1 for task in tasks if task.get("split") == "calibration")
    confirmatory = sum(1 for task in tasks if task.get("split") == "confirmatory")
    machine = sum(1 for task in tasks if task.get("judge") == "machine")
    critical = sum(1 for task in tasks if task.get("critical"))
    if total < 30:
        raise ValueError(f"基准至少 30 条任务，当前 {total}")
    if calibration < 10 or confirmatory < 20:
        raise ValueError(f"切分必须 ≥10/≥20，当前 {calibration}/{confirmatory}")
    if machine / total < 0.8:
        raise ValueError(f"机器可判定任务占比不足 80%：{machine}/{total}")
    if critical < 1:
        raise ValueError("至少需要 1 条 critical 任务用于全局安全闸")
    return {
        "total": total,
        "calibration": calibration,
        "confirmatory": confirmatory,
        "machine_judgeable": machine,
        "critical": critical,
    }


def build_prereg(
    *,
    bench_path: str | Path,
    hidden_path: str | Path,
    models: list[str],
    alpha: float = 0.05,
    delta_imp: float = 0.1,
    eps_ni: float = 0.05,
    mde: float = 0.2,
    bench_version: str = "m7-v1",
) -> dict[str, Any]:
    tasks = load_bench(bench_path)
    stats = validate_bench(tasks)
    return {
        "version": "1",
        "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bench_version": bench_version,
        "bench_path": str(bench_path),
        "hidden_path": str(hidden_path),
        "split": stats,
        "primary_endpoint": {
            "metric": "machine_judgeable_task_success_rate",
            "test": "mcnemar_exact",
            "alpha": alpha,
            "note": "只统计机器可判定任务；人工盲评未启用（无人工预算）",
        },
        "thresholds": {"delta_imp": delta_imp, "eps_ni": eps_ni, "mde": mde},
        "baseline": {
            "id": BASELINE_ID,
            "tier": BASELINE_TIER,
            "human_blind_eval": False,
            "sources": B1_SOURCES,
            "caveat": "开源专家模板基线，不等价于本研究盲写的人工基线；结论仅限机器可判定子集",
        },
        "models": models,
        "no_human_budget_mode": True,
        "labels": {
            "optimizing": "相对 B1-OSS 显著改善且达 delta_imp，并通过关键任务闸门",
            "compatible": "仅非劣（mean_diff ≥ -eps_ni），不得宣称更优",
            "rejected": "劣于 eps_ni 或关键任务失败",
        },
    }


def save_prereg(prereg: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(prereg, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def load_prereg(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for required in ("frozen_at", "primary_endpoint", "thresholds", "baseline", "models"):
        if required not in data:
            raise ValueError(f"预注册文件缺少字段：{required}")
    if not data["baseline"].get("human_blind_eval", False):
        data["baseline"]["mode"] = "oss-expert-template"  # 记录降级口径
    return data


def gate_for_model(
    report: EvalReport,
    comparison: dict[str, Any],
    prereg: dict[str, Any],
    *,
    critical_failures: int = 0,
) -> dict[str, Any]:
    thresholds = prereg["thresholds"]
    alpha = float(prereg["primary_endpoint"]["alpha"])
    mean_diff = float(comparison["mean_diff"])
    p_value = float(comparison["mcnemar"]["p_value"])
    ci_low = float(comparison["ci_low"])
    ci_high = float(comparison["ci_high"])

    if critical_failures > 0:
        label, reason = "rejected", f"{critical_failures} 条关键任务未通过"
    elif p_value < alpha and ci_low > 0 and mean_diff >= thresholds["delta_imp"]:
        label, reason = "optimizing", (
            f"McNemar p={p_value:.4f} < {alpha} 且 CI 下限 {ci_low:+.3f}>0，"
            f"均差 {mean_diff:+.3f} ≥ delta_imp {thresholds['delta_imp']}"
        )
    elif mean_diff >= -thresholds["eps_ni"]:
        label, reason = "compatible", f"仅非劣：均差 {mean_diff:+.3f} ≥ -eps_ni"
    else:
        label, reason = "rejected", f"劣于 eps_ni：均差 {mean_diff:+.3f}"

    return {
        "model": report.model_snapshot,
        "label": label,
        "reason": reason,
        "mean_diff": mean_diff,
        "ci": [ci_low, ci_high],
        "p_value": p_value,
        "n_tasks": comparison["n_tasks"],
        "critical_failures": critical_failures,
    }


def render_gate_markdown(
    prereg: dict[str, Any], results: list[dict[str, Any]], *, simulated: bool
) -> str:
    overall = "通过" if all(item["label"] != "rejected" for item in results) else "不通过"
    lines = [
        "# M7 门禁报告",
        "",
        f"- 预注册冻结时间：`{prereg['frozen_at']}`　基准版本：`{prereg['bench_version']}`",
        f"- 基线：`{prereg['baseline']['id']}`（{prereg['baseline']['tier']}，人工盲评：未启用）",
        f"- 主端点：{prereg['primary_endpoint']['metric']} / {prereg['primary_endpoint']['test']}",
        f"- 证据标签：{'⚠️ 模拟执行器（scripted）—— 仅验证门禁链路，不构成效果结论' if simulated else 'live 执行器'}"
        if simulated
        else f"- 证据标签：live 执行器（目标模型实测）",
        "",
        "## 逐模型结论",
        "",
        "| 模型 | 标签 | 均差 | 95% CI | McNemar p | 关键任务失败 | 依据 |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in results:
        lines.append(
            f"| {item['model']} | **{item['label']}** | {item['mean_diff']:+.3f} | "
            f"[{item['ci'][0]:+.3f}, {item['ci'][1]:+.3f}] | {item['p_value']:.4f} | "
            f"{item['critical_failures']} | {item['reason']} |"
        )
    lines += [
        "",
        f"## 总体结论：{overall}",
        "",
        f"> 口径限制：{prereg['baseline']['caveat']}。"
        "本报告不得表述为「超过人工专家」，也不得外推到未测模型或未测任务。",
        "",
    ]
    return "\n".join(lines)


def run_confirmation(
    *,
    prereg_path: str | Path,
    bench_path: str | Path,
    model_id: str,
    executor,
    out_path: str | Path,
    repeats: int = 3,
) -> dict[str, Any]:
    """在确证集上跑 champion vs B1-OSS，并按预注册阈值判定标签。"""
    prereg = load_prereg(prereg_path)
    tasks = [task for task in load_bench(bench_path) if task.get("split") == "confirmatory"]
    report = evaluate(
        build_candidates(model_id),
        tasks,
        executor,
        model_snapshot=f"{model_id}@{executor.name}",
        repeats=repeats,
        bench_version=str(prereg["bench_version"]),
    )
    comparison = compare(report, "champion", BASELINE_ID, margin=float(prereg["thresholds"]["eps_ni"]))

    critical_tasks = [task for task in tasks if task.get("critical")]
    critical_failures = 0
    for task in critical_tasks:
        result = report.summary.get(task["task_id"], {}).get("champion", {})
        if result.get("pass_rate", 0.0) < 1.0:
            critical_failures += 1

    gate = gate_for_model(report, comparison, prereg, critical_failures=critical_failures)
    markdown = render_gate_markdown(prereg, [gate], simulated=report.is_simulated)
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    return {"report": report, "comparison": comparison, "gate": gate, "markdown": markdown}
