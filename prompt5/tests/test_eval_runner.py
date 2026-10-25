"""M3 · 评测流水线测试：pilot 全链路、统计对比、报告口径、缓存隔离（DoD）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from prompt5.engine.pilot import build_candidates, run_pilot
from prompt5.modules.m5_eval.cache import EvalCache
from prompt5.modules.m5_eval.evalcase import EvalCase, aggregate_to_tasks
from prompt5.modules.m5_eval.l3_exec import Executor, ScriptedExecutor, judge_machine, run_case
from prompt5.modules.m5_eval.runner import Candidate, compare, evaluate, load_tasks, to_markdown

TASKS = Path(__file__).resolve().parents[1] / "benchmarks" / "tasks.jsonl"


class TestTasks:
    def test_load(self) -> None:
        tasks = load_tasks(TASKS)
        assert len(tasks) == 5
        assert {task["task_id"] for task in tasks} == {"t-p1", "t-p2", "t-p3", "t-p4", "t-p5"}
        assert all(task["judge"] == "machine" for task in tasks)

    def test_bad_file(self, tmp_path) -> None:
        bad = tmp_path / "bad.jsonl"
        bad.write_text('{"task_id": "x"}\n', encoding="utf-8")
        with pytest.raises(ValueError):
            load_tasks(bad)


class TestMachineJudge:
    @pytest.mark.parametrize(
        "spec,output,expected",
        [
            ({"kind": "exact_match", "expected": "投诉"}, "投诉", True),
            ({"kind": "exact_match", "expected": "投诉"}, "投诉。", False),
            ({"kind": "contains", "all": ["a", "b"]}, "x a y b", True),
            ({"kind": "checklist", "items": ["姓名"]}, "无", False),
            ({"kind": "numeric", "expected": 1280, "tolerance": 0.01}, "总额 1280 元", True),
            ({"kind": "numeric", "expected": 1280, "tolerance": 0.01}, "总额 1200 元", False),
            ({"kind": "unknown"}, "x", False),
        ],
    )
    def test_specs(self, spec: dict, output: str, expected: bool) -> None:
        assert judge_machine(output, spec).passed is expected


class _AlwaysEmpty(Executor):
    name = "empty"

    def execute(self, prompt: str, task: dict) -> str:
        return ""


class TestEvalCake:
    def test_case_id_is_tuple_hash(self) -> None:
        case = EvalCase(task_id="t1", model_snapshot="m1", seed=1, repeat_idx=0)
        assert len(case.case_id) == 64
        assert case.case_id == EvalCase("t1", "m1", 1, 0).case_id
        assert case.case_id != EvalCase("t1", "m2", 1, 0).case_id

    def test_aggregate_three_layers(self) -> None:
        rows = []
        for repeat in range(3):
            rows.append(run_case(ScriptedExecutor(), {"task_id": "t", "machine_judge": {"kind": "exact_match", "expected": "a"}, "simulation": {"gold": "a"}}, "p", variant="c", model_snapshot="m", seed=1, repeat_idx=repeat))
        summary = aggregate_to_tasks(rows)
        assert summary["t"]["c"]["pass_rate"] == 1.0
        assert summary["t"]["c"]["cases"] == 3.0


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    out = tmp_path_factory.mktemp("reports") / "pilot.md"
    return run_pilot(TASKS, out)


class TestPilot:

    def test_pass_rates(self, result) -> None:
        report, comparison, _ = result
        assert len(report.rows) == 5 * 2 * 3
        assert comparison["rates_first"] == [1.0, 1.0, 1.0, 1.0, 1.0]
        assert comparison["rates_second"] == [0.0, 0.0, 0.0, 1.0, 1.0]
        assert comparison["mean_diff"] == pytest.approx(0.6)

    def test_stats(self, result) -> None:
        _, comparison, _ = result
        assert comparison["mcnemar"] == {"b": 3, "c": 0, "p_value": pytest.approx(0.25)}
        assert comparison["wilcoxon"]["p_value"] == pytest.approx(0.25)
        assert comparison["ci_low"] > 0

    def test_report_states_limitations(self, result) -> None:
        _, _, markdown = result
        assert "模拟执行器" in markdown
        assert "功效不足" in markdown
        assert "不构成效果证据" in markdown
        assert "TOST" in markdown

    def test_report_written(self, result, tmp_path_factory) -> None:
        report, _, markdown = result
        assert report.bench_version == "pilot-v1"
        assert markdown.startswith("# M3 Pilot 评测报告")


class TestCacheIsolation:
    def test_same_inputs_hit_cache(self) -> None:
        tasks = load_tasks(TASKS)
        cache = EvalCache()
        candidates = [build_candidates("deepseek")[0]]
        first = evaluate(candidates, tasks, ScriptedExecutor(), model_snapshot="m", repeats=3, cache=cache)
        assert (first.cache_stats["hits"], first.cache_stats["misses"]) == (0, 15)
        before = cache.stats()
        second = evaluate(candidates, tasks, ScriptedExecutor(), model_snapshot="m", repeats=3, cache=cache)
        after = second.cache_stats
        assert after["hits"] - before["hits"] == 15
        assert after["misses"] - before["misses"] == 0

    def test_model_change_misses(self) -> None:
        tasks = load_tasks(TASKS)
        cache = EvalCache()
        candidates = [build_candidates("deepseek")[0]]
        first = evaluate(candidates, tasks, ScriptedExecutor(), model_snapshot="m1", repeats=3, cache=cache)
        before = cache.stats()
        report = evaluate(candidates, tasks, ScriptedExecutor(), model_snapshot="m2", repeats=3, cache=cache)
        assert report.cache_stats["hits"] - before["hits"] == 0
        assert report.cache_stats["misses"] - before["misses"] == 15

    def test_judge_change_misses(self) -> None:
        tasks = load_tasks(TASKS)
        cache = EvalCache()
        candidates = [build_candidates("deepseek")[1]]
        evaluate(candidates, tasks, ScriptedExecutor(), model_snapshot="m", repeats=3, judge_id="judge-a", cache=cache)
        before = cache.stats()
        report = evaluate(candidates, tasks, ScriptedExecutor(), model_snapshot="m", repeats=3, judge_id="judge-b", cache=cache)
        assert report.cache_stats["hits"] - before["hits"] == 0

    def test_bench_change_misses(self) -> None:
        tasks = load_tasks(TASKS)
        cache = EvalCache()
        candidates = [build_candidates("deepseek")[1]]
        evaluate(candidates, tasks, ScriptedExecutor(), model_snapshot="m", repeats=3, bench_version="v1", cache=cache)
        before = cache.stats()
        report = evaluate(candidates, tasks, ScriptedExecutor(), model_snapshot="m", repeats=3, bench_version="v2", cache=cache)
        assert report.cache_stats["hits"] - before["hits"] == 0

    def test_key_components(self) -> None:
        base = EvalCache.key(model="m", judge="j", bench="b", repeats="3")
        assert base == EvalCache.key(model="m", judge="j", bench="b", repeats="3")
        for changed in (
            EvalCache.key(model="m2", judge="j", bench="b", repeats="3"),
            EvalCache.key(model="m", judge="j2", bench="b", repeats="3"),
            EvalCache.key(model="m", judge="j", bench="b2", repeats="3"),
        ):
            assert changed != base


class TestDegenerate:
    def test_all_fail_report(self) -> None:
        tasks = load_tasks(TASKS)
        candidates = [Candidate("e", lambda task: "")]
        report = evaluate(candidates, tasks, _AlwaysEmpty(), model_snapshot="m", repeats=3)
        comparison = compare(report, "e", "e")
        assert comparison["mean_diff"] == 0.0
        markdown = to_markdown(report, comparison)
        assert "未检出显著差异" in markdown

    def test_repeats_must_match_seeds(self) -> None:
        tasks = load_tasks(TASKS)[:1]
        with pytest.raises(ValueError):
            evaluate([build_candidates("deepseek")[1]], tasks, ScriptedExecutor(), model_snapshot="m", repeats=2, seeds=(1,))
