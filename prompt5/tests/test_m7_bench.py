"""M7 骨架：基准校验、B1-OSS 基线、预注册冻结、门禁三分支。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prompt5.modules.m5_eval.l3_exec import ScriptedExecutor
from prompt5.modules.m7_bench import (
    B1_SOURCES,
    B1_TEMPLATES,
    BASELINE_ID,
    b1_oss_builder,
    build_candidates,
    build_prereg,
    gate_for_model,
    load_bench,
    load_prereg,
    run_confirmation,
    save_prereg,
    validate_bench,
)

BENCH = Path(__file__).resolve().parents[1] / "benchmarks" / "tasks_m7.jsonl"
HIDDEN = Path(__file__).resolve().parents[1] / "benchmarks" / "hidden" / "tasks_hidden.jsonl"
PREREG = Path(__file__).resolve().parents[1] / "benchmarks" / "preregistration.json"


class TestBench:
    def test_stats(self) -> None:
        tasks = load_bench(BENCH)
        stats = validate_bench(tasks)
        assert stats["total"] == 30
        assert stats["calibration"] == 10
        assert stats["confirmatory"] == 20
        assert stats["machine_judgeable"] >= 24
        assert stats["critical"] >= 1

    def test_hidden_is_separate(self) -> None:
        hidden = load_bench(HIDDEN)
        assert len(hidden) == 10
        assert {task["split"] for task in hidden} == {"hidden"}
        bench_ids = {task["task_id"] for task in load_bench(BENCH)}
        assert not ({task["task_id"] for task in hidden} & bench_ids)

    def test_insufficient_bench_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_bench(load_bench(BENCH)[:5])


class TestBaseline:
    def test_templates_cover_all_types(self) -> None:
        types = {task["type"] for task in load_bench(BENCH)}
        assert types <= set(B1_TEMPLATES)

    def test_builder_injects_brief(self) -> None:
        task = load_bench(BENCH)[0]
        prompt = b1_oss_builder(task)
        assert task["prompt_brief"] in prompt

    def test_unknown_type_falls_back(self) -> None:
        prompt = b1_oss_builder({"type": "unknown", "prompt_brief": "做点事"})
        assert "做点事" in prompt

    def test_sources_have_license(self) -> None:
        assert len(B1_SOURCES) >= 2
        assert all(source["license"] for source in B1_SOURCES)
        assert {source["license"] for source in B1_SOURCES} >= {"CC0-1.0", "Apache-2.0"}

    def test_candidates_pair(self) -> None:
        names = [candidate.name for candidate in build_candidates("deepseek")]
        assert names == ["champion", BASELINE_ID]


class TestPrereg:
    def test_fields(self, tmp_path) -> None:
        prereg = build_prereg(bench_path=BENCH, hidden_path=HIDDEN, models=["deepseek"])
        assert prereg["baseline"]["human_blind_eval"] is False
        assert prereg["baseline"]["tier"] == "oss-expert-template"
        assert prereg["split"]["confirmatory"] == 20
        assert prereg["primary_endpoint"]["test"] == "mcnemar_exact"

        path = save_prereg(prereg, tmp_path / "prereg.json")
        loaded = load_prereg(path)
        assert loaded["frozen_at"] == prereg["frozen_at"]

    def test_missing_field_rejected(self, tmp_path) -> None:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"frozen_at": "x"}), encoding="utf-8")
        with pytest.raises(ValueError):
            load_prereg(path)


class TestGate:
    def _prereg(self) -> dict:
        return build_prereg(bench_path=BENCH, hidden_path=HIDDEN, models=["deepseek"])

    def _report(self):
        from prompt5.modules.m5_eval.runner import evaluate

        tasks = [t for t in load_bench(BENCH) if t["split"] == "confirmatory"]
        return evaluate(
            build_candidates("deepseek"), tasks, ScriptedExecutor(),
            model_snapshot="deepseek@scripted", repeats=3,
        )

    def _comparison(self, mean_diff: float, p: float, ci: list[float]) -> dict:
        return {"mean_diff": mean_diff, "mcnemar": {"p_value": p},
                "ci_low": ci[0], "ci_high": ci[1], "n_tasks": 20}

    def test_optimizing(self) -> None:
        result = gate_for_model(self._report(), self._comparison(0.5, 0.001, [0.3, 0.7]), self._prereg())
        assert result["label"] == "optimizing"

    def test_compatible_only(self) -> None:
        result = gate_for_model(self._report(), self._comparison(0.02, 0.5, [-0.02, 0.06]), self._prereg())
        assert result["label"] == "compatible"

    def test_rejected_when_regression(self) -> None:
        result = gate_for_model(self._report(), self._comparison(-0.3, 0.01, [-0.5, -0.1]), self._prereg())
        assert result["label"] == "rejected"

    def test_critical_failure_forces_rejected(self) -> None:
        result = gate_for_model(
            self._report(), self._comparison(0.5, 0.001, [0.3, 0.7]), self._prereg(), critical_failures=1
        )
        assert result["label"] == "rejected"
        assert "关键任务" in result["reason"]


class TestRunConfirmation:
    def test_scripted_gate(self, tmp_path) -> None:
        prereg_path = save_prereg(
            build_prereg(bench_path=BENCH, hidden_path=HIDDEN, models=["deepseek"]),
            tmp_path / "prereg.json",
        )
        outcome = run_confirmation(
            prereg_path=prereg_path, bench_path=BENCH, model_id="deepseek",
            executor=ScriptedExecutor(), out_path=tmp_path / "gate.md",
        )
        assert outcome["gate"]["label"] in {"optimizing", "compatible", "rejected"}
        assert "模拟执行器" in outcome["markdown"]
        assert "不得表述为「超过人工专家」" in outcome["markdown"]
        assert "b1-oss" in outcome["markdown"]
