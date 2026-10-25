"""命令行入口：`python -m prompt5.cli demo-zero --task "..."`。

M2 只需实现 demo-zero（DoD）；其余子命令随里程碑增加。
LLM 默认 Mock（离线确定性），`--llm openai` 时从配置读取生成器端点。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine.flow_zero import run_zero
from .llm.client import LLMClient, MockLLM
from .modules.m1_extractor import extract_intent

__all__ = ["main"]


def _load_llm(kind: str, config_path: str | None) -> LLMClient:
    if kind == "mock":
        return MockLLM()
    from .config import ConfigError, load_config
    from .llm.roles import build_llm

    cfg = load_config(config_path or "config.example.yaml")
    try:
        return build_llm("generator", cfg.data)
    except ConfigError as exc:
        raise SystemExit(f"模型配置不可用：{exc}") from exc


def _print_report(result, *, model_id: str, verbose: bool) -> None:
    frame = result.frame
    print("========== IntentFrame ==========")
    print(f"task_type : {frame.task_type}")
    print(f"source    : {frame.source}")
    print(f"missing   : {frame.missing or '[]'}")
    for assumption in frame.assumptions:
        print(f"assumption: {assumption}")

    print("\n========== IR ==========")
    ir = result.ir
    print(f"ir_id     : {ir.ir_id}")
    print(f"version   : {ir.version}   lineage: {ir.lineage_id}")
    print(f"checksum  : {ir.checksum}")
    print(f"strategy  : {ir.created.get('strategy_id')}")
    if verbose:
        print(json.dumps(ir.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2))
    else:
        print(f"role      : {ir.slots.role}")
        print(f"outcome   : {ir.slots.goal.outcome}")
        print(f"must      : {ir.slots.constraints.must}")
        print(f"workflow  : {ir.slots.workflow}")

    print(f"\n========== Rendered ({model_id}) ==========")
    print(result.rendered.text)
    print(f"cache_key : {result.rendered.cache_key}")

    print("========== L1 Report ==========")
    report = result.l1
    print(f"passed={report.passed} score={report.score:.3f} tokens≈{report.token_estimate}")
    for finding in report.findings:
        print(f"- [{finding.severity}] {finding.code}: {finding.message} {('@' + finding.loc) if finding.loc else ''}")
    if not report.findings:
        print("- 无问题")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prompt5.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo-zero", help="从零生成最小闭环（流程 A）")
    demo.add_argument("--task", required=True, help="一句话任务描述")
    demo.add_argument("--model", default="glm5", help="目标模型卡（默认 glm5）")
    demo.add_argument("--llm", choices=["mock", "openai"], default="mock")
    demo.add_argument("--config", default=None)
    demo.add_argument("--budget", type=int, default=4000)
    demo.add_argument("--json", action="store_true", help="输出完整 IR JSON")
    demo.add_argument("--ir-id", default=None)

    config_parser = sub.add_parser("config", help="配置检查")
    config_sub = config_parser.add_subparsers(dest="config_action", required=True)
    check_cmd = config_sub.add_parser("check", help="校验端点/密钥/角色绑定并打印生效配置")
    check_cmd.add_argument("--config", default=None)

    pilot = sub.add_parser("pilot", help="M3 pilot：候选 vs B2（离线执行器）")
    pilot.add_argument("--tasks", default="benchmarks/tasks.jsonl")
    pilot.add_argument("--out", default="reports/m3-pilot.md")
    pilot.add_argument("--repeats", type=int, default=3)
    pilot.add_argument("--margin", type=float, default=0.1)
    pilot.add_argument("--quiet", action="store_true", help="只打印摘要，不打印完整 markdown")

    extract = sub.add_parser("extract", help="只跑意图解析")
    extract.add_argument("--task", required=True)
    extract.add_argument("--llm", choices=["mock", "openai"], default="mock")
    extract.add_argument("--config", default=None)

    args = parser.parse_args(argv)

    if args.command == "config":
        from .config import load_config, validate_config
        from .llm.roles import describe_roles

        path = args.config or "config.example.yaml"
        loaded = load_config(path)
        issues = validate_config(loaded.data)
        print(f"config: {loaded.source}")
        if loaded.missing_env:
            print(f"missing env: {sorted(set(loaded.missing_env))}")

        print("\nproviders:")
        for name, raw in (loaded.data.get("providers") or {}).items():
            raw = raw or {}
            env_name = raw.get("api_key_env", "")
            import os

            key_state = "已配置" if (env_name and os.environ.get(env_name)) or raw.get("api_key") else "未配置"
            print(f"  - {name:<9} {raw.get('base_url','<未设置>')}  key={key_state}")

        print("\nroles:")
        for row in describe_roles(loaded.data):
            if row["status"] == "ok":
                print(f"  - {row['role']:<11} -> {row['provider']}/{row['model']}  ({row['base_url']}, key={row['api_key']})")
            else:
                print(f"  - {row['role']:<11} ERROR: {row['error']}")

        print("\nissues:")
        if not issues:
            print("  - 无")
        for issue in issues:
            print(f"  - [{issue.level}] {issue.code} {issue.field}: {issue.message}")

        errors = sum(1 for issue in issues if issue.level == "error")
        warns = sum(1 for issue in issues if issue.level == "warn")
        print(f"\nerrors={errors} warnings={warns}")
        return 1 if errors else 0

    if args.command == "pilot":
        from .engine.pilot import run_pilot

        report, comparison, markdown = run_pilot(
            args.tasks, args.out, repeats=args.repeats, margin=args.margin
        )
        if not args.quiet:
            print(markdown)
        else:
            print(
                f"pilot done: tasks={len(report.tasks)} mean_diff={comparison['mean_diff']:+.3f} "
                f"CI=[{comparison['ci_low']:+.3f},{comparison['ci_high']:+.3f}] "
                f"mcnemar_p={comparison['mcnemar']['p_value']:.4f} -> {args.out}"
            )
        return 0

    if args.command == "extract":
        llm = _load_llm(args.llm, args.config)
        frame = extract_intent(args.task, llm=llm)
        print(json.dumps(frame.model_dump(), ensure_ascii=False, indent=2))
        return 0

    llm = _load_llm(args.llm, args.config)
    result = run_zero(
        args.task,
        llm=llm,
        model_id=args.model,
        ir_id=args.ir_id,
        token_budget=args.budget,
    )
    _print_report(result, model_id=args.model, verbose=args.json)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
