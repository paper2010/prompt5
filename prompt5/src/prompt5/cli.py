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

    iterate = sub.add_parser("iterate", help="M4：种子提示词迭代（反解 → 补丁 → 回归保护）")
    iterate.add_argument("--seed-file", required=True)
    iterate.add_argument("--task", default="", help="改进要求，如：请用表格输出，必须结论先行")
    iterate.add_argument("--model", default="glm5")
    iterate.add_argument("--rounds", type=int, default=2)
    iterate.add_argument("--db", default="prompt5.db")
    iterate.add_argument("--tasks", default="benchmarks/tasks.jsonl")
    iterate.add_argument("--no-regression", action="store_true")

    config_parser = sub.add_parser("config", help="配置检查")
    config_sub = config_parser.add_subparsers(dest="config_action", required=True)
    check_cmd = config_sub.add_parser("check", help="校验端点/密钥/角色绑定并打印生效配置")
    check_cmd.add_argument("--config", default=None)

    m7 = sub.add_parser("m7", help="M7 基准：预注册与门禁")
    m7_sub = m7.add_subparsers(dest="m7_action", required=True)
    m7_init = m7_sub.add_parser("init", help="生成预注册文件（冻结前）")
    m7_init.add_argument("--tasks", default="benchmarks/tasks_m7.jsonl")
    m7_init.add_argument("--hidden", default="benchmarks/hidden/tasks_hidden.jsonl")
    m7_init.add_argument("--models", default="deepseek")
    m7_init.add_argument("--out", default="benchmarks/preregistration.json")
    m7_run = m7_sub.add_parser("run", help="在确证集上跑门禁")
    m7_run.add_argument("--prereg", default="benchmarks/preregistration.json")
    m7_run.add_argument("--tasks", default="benchmarks/tasks_m7.jsonl")
    m7_run.add_argument("--target", default="deepseek")
    m7_run.add_argument("--executor", choices=["scripted", "live"], default="scripted")
    m7_run.add_argument("--repeats", type=int, default=3)
    m7_run.add_argument("--out", default="reports/m7-gate.md")
    m7_run.add_argument("--config", default=None)

    probe = sub.add_parser("probe", help="连通性探针：向已配置端点发最小请求")
    probe.add_argument("--config", default=None)
    probe.add_argument("--target", default=None, help="只测某个 target；缺省测全部")

    pilot = sub.add_parser("pilot", help="M3 pilot：候选 vs B2（可切真实执行器/L2 裁判）")
    pilot.add_argument("--tasks", default="benchmarks/tasks.jsonl")
    pilot.add_argument("--out", default="reports/m3-pilot.md")
    pilot.add_argument("--repeats", type=int, default=3)
    pilot.add_argument("--margin", type=float, default=0.1)
    pilot.add_argument("--model", default="deepseek", help="渲染用模型卡（默认主模型 deepseek）")
    pilot.add_argument("--executor", choices=["scripted", "live"], default="scripted")
    pilot.add_argument("--target", default=None, help="live 模式下的被测目标名（默认 primary）")
    pilot.add_argument("--judge", choices=["off", "l2"], default="off")
    pilot.add_argument("--config", default=None)
    pilot.add_argument("--quiet", action="store_true", help="只打印摘要，不打印完整 markdown")

    extract = sub.add_parser("extract", help="只跑意图解析")
    extract.add_argument("--task", required=True)
    extract.add_argument("--llm", choices=["mock", "openai"], default="mock")
    extract.add_argument("--config", default=None)

    args = parser.parse_args(argv)

    if args.command == "iterate":
        from .engine.iterate import run_iterate, select_regression_tasks
        from .ledger import Ledger
        from .modules.m1_seed import parse_seed_prompt
        from .modules.m3_cards import render as render_ir
        from .modules.m5_eval.l1_rules import check as l1_check
        from .modules.m5_eval.runner import load_tasks
        from .store.migrate import init_db

        seed_text = Path(args.seed_file).read_text(encoding="utf-8")
        ledger = Ledger(init_db(args.db))
        seed = parse_seed_prompt(seed_text)
        stored = ledger.create_ir(seed.payload() | {"checksum": seed.checksum})

        regression_tasks = []
        if not args.no_regression and Path(args.tasks).exists():
            baseline_render = render_ir(stored, args.model).text
            regression_tasks = select_regression_tasks(load_tasks(args.tasks), baseline_render)

        outcome = run_iterate(
            stored,
            args.task,
            ledger,
            model_id=args.model,
            max_rounds=args.rounds,
            regression_tasks=regression_tasks,
        )

        print("========== Seed ==========")
        print(f"ir_id     : {stored.ir_id}")
        print(f"version   : {stored.version}   checksum: {stored.checksum[:16]}…")
        print(f"role      : {stored.slots.role}")
        print(f"format    : {stored.slots.output.format}")

        print("\n========== Iterate ==========")
        print(f"applied   : {[p.patch_id[:10] for p in outcome.applied]}")
        print(f"rejected  : {outcome.rejected or '[]'}")
        print(f"regression: {'checked ' + str(outcome.regression.get('tasks_checked', 0)) + ' tasks' if outcome.regression else 'skipped'}")
        print(f"history   : {ledger.history(stored.ir_id)}")

        final = outcome.final_ir
        print("\n========== Final IR ==========")
        print(f"version   : {final.version}   checksum: {final.checksum[:16]}…")
        print(f"format    : {final.slots.output.format}")
        print(f"must      : {final.slots.constraints.must}")

        rendered = render_ir(final, args.model)
        print(f"\n========== Rendered ({args.model}) ==========")
        print(rendered.text)

        before = l1_check(stored, render_ir(stored, args.model).text)
        after = l1_check(final, rendered.text)
        print("========== L1 ==========")
        print(f"before: passed={before.passed} score={before.score:.3f}")
        print(f"after : passed={after.passed} score={after.score:.3f}")
        return 0 if after.passed else 1

    if args.command == "config":
        from .config import load_config, validate_config
        from .llm.roles import describe_roles, describe_targets

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
                print(f"  - {row['role']:<15} -> {row['provider']}/{row['model']}  ({row['base_url']}, key={row['api_key']})")
            else:
                print(f"  - {row['role']:<15} ERROR: {row['error']}")

        print("\ntargets (L3 执行端点):")
        for row in describe_targets(loaded.data):
            if row["status"] == "ok":
                mark = "  ← primary" if row["primary"] else ""
                print(f"  - {row['target']:<9} -> {row['provider']}/{row['model']}  label={row['label']}  ({row['base_url']}){mark}")
            else:
                print(f"  - {row['target']:<9} ERROR: {row['error']}")

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
        from .config import load_config, primary_target, resolve_target
        from .engine.pilot import run_pilot
        from .llm.roles import build_executor, build_judge

        executor = None
        judge = None
        judge_meta = None
        model_id = args.model

        if args.executor == "live" or args.judge == "l2":
            from .config import ConfigError

            data = load_config(args.config or "config.example.yaml").data
            try:
                if args.executor == "live":
                    executor, meta = build_executor(data, args.target)
                    model_id = meta["target"]
                    print(f"live executor: {meta['provider']}/{meta['model']}（{meta['base_url']}）")
                if args.judge == "l2":
                    target_name = args.target or primary_target(data)
                    provider, _, _ = resolve_target(data, target_name)
                    judge, judge_meta = build_judge(data, provider.name)
                    print(f"l2 judge: {judge_meta['provider']}/{judge_meta['model']}")
            except ConfigError as exc:
                raise SystemExit(f"配置不可用：{exc}") from exc

        report, comparison, markdown = run_pilot(
            args.tasks,
            args.out,
            repeats=args.repeats,
            margin=args.margin,
            model_id=model_id,
            executor=executor,
            judge=judge,
            judge_meta=judge_meta,
        )
        if not args.quiet:
            print(markdown)
        else:
            print(
                f"pilot done: executor={report.executor_name} tasks={len(report.tasks)} "
                f"mean_diff={comparison['mean_diff']:+.3f} "
                f"CI=[{comparison['ci_low']:+.3f},{comparison['ci_high']:+.3f}] "
                f"mcnemar_p={comparison['mcnemar']['p_value']:.4f} -> {args.out}"
            )
        return 0

    if args.command == "m7":
        from .modules.m7_bench import build_prereg, run_confirmation, save_prereg

        if args.m7_action == "init":
            models = [item.strip() for item in args.models.split(",") if item.strip()]
            prereg = build_prereg(
                bench_path=args.tasks, hidden_path=args.hidden, models=models
            )
            path = save_prereg(prereg, args.out)
            stats = prereg["split"]
            print(f"prereg written: {path}")
            print(f"tasks={stats['total']} calibration={stats['calibration']} "
                  f"confirmatory={stats['confirmatory']} machine={stats['machine_judgeable']}")
            print(f"baseline={prereg['baseline']['id']} human_blind_eval="
                  f"{prereg['baseline']['human_blind_eval']}")
            return 0

        from .config import ConfigError, load_config
        from .llm.roles import build_executor

        executor = None
        if args.executor == "live":
            try:
                executor, meta = build_executor(load_config(args.config or "config.example.yaml").data, args.target)
            except ConfigError as exc:
                raise SystemExit(f"配置不可用：{exc}") from exc
            print(f"live executor: {meta['provider']}/{meta['model']}")

        from .modules.m5_eval.l3_exec import ScriptedExecutor

        outcome = run_confirmation(
            prereg_path=args.prereg,
            bench_path=args.tasks,
            model_id=args.target,
            executor=executor or ScriptedExecutor(),
            out_path=args.out,
            repeats=args.repeats,
        )
        gate = outcome["gate"]
        print(f"gate: model={gate['model']} label={gate['label']} "
              f"mean_diff={gate['mean_diff']:+.3f} p={gate['p_value']:.4f} "
              f"critical_failures={gate['critical_failures']}")
        print(f"report: {args.out}")
        return 0

    if args.command == "probe":
        from time import perf_counter

        from .config import ConfigError, load_config
        from .llm.client import LLMError
        from .llm.roles import build_target_client

        data = load_config(args.config or "config.example.yaml").data
        names = [args.target] if args.target else list((data.get("targets") or {}).keys())
        failures = 0
        for name in names:
            try:
                client, meta = build_target_client(data, name)
                started = perf_counter()
                reply = client.chat([{"role": "user", "content": "ping"}], max_tokens=8, temperature=0.0)
                elapsed = (perf_counter() - started) * 1000
                print(
                    f"OK   {name:<9} {meta['provider']}/{meta['model']}  {elapsed:.0f}ms  reply={reply[:40]!r}"
                )
            except (ConfigError, LLMError) as exc:
                failures += 1
                print(f"FAIL {name:<9} {type(exc).__name__}: {str(exc)[:160]}")
            except Exception as exc:  # noqa: BLE001 - 探针需覆盖未知失败
                failures += 1
                print(f"FAIL {name:<9} {type(exc).__name__}: {str(exc)[:160]}")
        print(f"\nprobed={len(names)} failures={failures}")
        return 0 if failures == 0 else 1

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
