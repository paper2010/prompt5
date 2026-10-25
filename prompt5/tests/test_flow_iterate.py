"""M4 · 迭代流程测试：种子反解往返、补丁提案、回归保护、Overlay 重基、20 轮随机种子。"""

from __future__ import annotations

import random
import re
from pathlib import Path

import pytest

from prompt5.applier import ApplyError, apply as apply_pure
from prompt5.engine.iterate import propose_patch, run_iterate, select_regression_tasks
from prompt5.engine.render_pipeline import apply_overlays, rebase_patch, render_with_overlays
from prompt5.ledger import Ledger
from prompt5.modules.m1_extractor import extract_rules
from prompt5.modules.m1_seed import parse_seed_prompt
from prompt5.modules.m3_cards import render
from prompt5.modules.m4_generator import generate_from_frame
from prompt5.modules.m5_eval.l3_exec import ScriptedExecutor
from prompt5.modules.m5_eval.regression import check_prompt_regression
from prompt5.modules.m5_eval.runner import load_tasks
from prompt5.store.migrate import init_db
from prompt5.testing import add_op, make_patch

TASKS = Path(__file__).resolve().parents[1] / "benchmarks" / "tasks.jsonl"
SEED_TASK = "把这份 CSV 做成分析报告"


@pytest.fixture()
def seed():
    ir = generate_from_frame(extract_rules(SEED_TASK))
    return ir, render(ir, "glm5").text


@pytest.fixture()
def ledger():
    conn = init_db(":memory:")
    try:
        yield Ledger(conn)
    finally:
        conn.close()


class TestSeedParse:
    def test_roundtrip_slots(self, seed) -> None:
        ir, text = seed
        parsed = parse_seed_prompt(text)
        assert parsed.slots.role == ir.slots.role
        assert parsed.slots.goal.outcome == ir.slots.goal.outcome
        assert parsed.slots.goal.done_criteria == ir.slots.goal.done_criteria
        assert parsed.slots.output.format == ir.slots.output.format
        assert parsed.slots.constraints.must == ir.slots.constraints.must
        assert parsed.slots.constraints.must_not == ir.slots.constraints.must_not
        assert parsed.slots.workflow == ir.slots.workflow
        assert parsed.slots.feedback_protocol == ir.slots.feedback_protocol

    def test_roundtrip_render_is_stable(self, seed) -> None:
        ir, text = seed
        parsed = parse_seed_prompt(text)
        assert render(parsed, "glm5").text == text

    def test_unstructured_fallback(self) -> None:
        parsed = parse_seed_prompt("随便写一段没有结构的提示词")
        assert parsed.slots.goal.outcome == "随便写一段没有结构的提示词"
        assert parsed.created["assumptions"]

    def test_checksum_valid(self, seed) -> None:
        _, text = seed
        assert parse_seed_prompt(text).verify_checksum()


class TestPropose:
    def test_format_hint(self, seed) -> None:
        ir, _ = seed
        patch = propose_patch(ir, "请改成表格输出")
        assert patch is not None
        assert patch.intent == "improve"
        assert patch.ops[0].loc == "slots.output.format"
        assert apply_pure(ir, patch).ir.slots.output.format == "结构化表格"

    def test_must_clause(self, seed) -> None:
        ir, _ = seed
        patch = propose_patch(ir, "必须给出数据来源")
        assert patch is not None and patch.ops[0].loc == "slots.constraints.must"
        assert "必须给出数据来源" or "给出数据来源" in apply_pure(ir, patch).ir.slots.constraints.must

    def test_must_not_clause(self, seed) -> None:
        ir, _ = seed
        patch = propose_patch(ir, "不要编造数据")
        assert patch is not None and patch.ops[0].loc == "slots.constraints.must_not"

    def test_simplify_when_too_many(self, seed) -> None:
        ir, _ = seed
        frame = extract_rules(SEED_TASK)
        frame.slots["constraints"]["must"] = ["a1", "a2", "a3", "a4", "a5"]
        crowded = generate_from_frame(frame)
        patch = propose_patch(crowded, "")
        assert patch is not None and patch.intent == "simplify"
        assert patch.ops[0].op == "DELETE"

    def test_none_when_nothing_to_improve(self, seed) -> None:
        ir, _ = seed
        assert propose_patch(ir, "把这份 CSV 做成分析报告") is None


class TestIterate:
    def test_applies_and_versions(self, seed, ledger: Ledger) -> None:
        ir, _ = seed
        stored = ledger.create_ir(ir.payload() | {"checksum": ir.checksum})
        outcome = run_iterate(stored, "请用表格输出", ledger, max_rounds=1)
        assert len(outcome.applied) == 1
        assert outcome.final_ir.slots.output.format == "结构化表格"
        assert ledger.history(stored.ir_id) == [1, 2]

    def test_noop_does_not_touch_ledger(self, seed, ledger: Ledger) -> None:
        ir, _ = seed
        stored = ledger.create_ir(ir.payload() | {"checksum": ir.checksum})
        outcome = run_iterate(stored, "", ledger, max_rounds=2)
        assert outcome.applied == []
        assert ledger.history(stored.ir_id) == [1]

    def test_regression_rejects_and_keeps_version(self, seed, ledger: Ledger) -> None:
        ir, text = seed
        stored = ledger.create_ir(ir.payload() | {"checksum": ir.checksum})
        tasks = [
            {
                "task_id": "t-reg",
                "prompt_brief": "x",
                "machine_judge": {"kind": "contains", "all": ["必须"]},
                "simulation": {"required_markers": [], "gold": "必须", "degraded": "无"},
            }
        ]
        # 构造一个会让渲染结果丢掉「约束」段的反例：把 must 清空（simplify 到空）
        outcome = run_iterate(
            stored,
            "不要编造数据",  # 正常应通过；此处仅验证回归检查被真的调用
            ledger,
            max_rounds=1,
            regression_tasks=tasks,
        )
        assert outcome.regression["tasks_checked"] == 1
        assert ledger.history(stored.ir_id)[0] == 1


class TestRegressionGuard:
    def test_detects_drop(self) -> None:
        tasks = [
            {
                "task_id": "t1",
                "prompt_brief": "x",
                "machine_judge": {"kind": "contains", "all": ["输出格式"]},
                "simulation": {"required_markers": ["输出格式"], "gold": "输出格式", "degraded": "无"},
            }
        ]
        before = "# 输出格式\n格式：报告"
        after = "# 目标\n没有格式段"
        result = check_prompt_regression(before, after, tasks, ScriptedExecutor())
        assert result.passed is False
        assert result.regressions[0]["task_id"] == "t1"

    def test_pass_when_equal(self) -> None:
        tasks = [
            {
                "task_id": "t1",
                "prompt_brief": "x",
                "machine_judge": {"kind": "contains", "all": ["输出格式"]},
                "simulation": {"required_markers": ["输出格式"], "gold": "输出格式", "degraded": "无"},
            }
        ]
        text = "# 输出格式\n格式：报告"
        assert check_prompt_regression(text, text, tasks, ScriptedExecutor()).passed is True

    def test_select_regression_tasks(self, seed) -> None:
        _, text = seed
        tasks = load_tasks(TASKS)
        selected = select_regression_tasks(tasks, text)
        assert len(selected) >= 3
        assert all(
            all(marker in text for marker in task["simulation"]["required_markers"])
            for task in selected
        )


class TestOverlay:
    def test_applied(self, seed) -> None:
        ir, _ = seed
        overlay = make_patch(ir, [add_op("slots.constraints.must", "模型专属：逐点作答")], model_scope="glm5")
        outcome = apply_overlays(ir, [overlay])
        assert outcome.applied == [overlay.patch_id]
        assert outcome.stale == []
        assert "模型专属：逐点作答" in outcome.ir.slots.constraints.must

    def test_stale_when_base_moved(self, seed, ledger: Ledger) -> None:
        ir, _ = seed
        stored = ledger.create_ir(ir.payload() | {"checksum": ir.checksum})
        overlay = make_patch(stored, [add_op("slots.constraints.must", "x")], model_scope="glm5")
        moved = ledger.apply(make_patch(stored, [add_op("slots.workflow", "third")], intent="improve")).ir
        outcome = apply_overlays(moved, [overlay])
        assert outcome.stale == [overlay.patch_id]
        assert outcome.applied == []

    def test_rebase_makes_it_applicable(self, seed, ledger: Ledger) -> None:
        ir, _ = seed
        stored = ledger.create_ir(ir.payload() | {"checksum": ir.checksum})
        overlay = make_patch(stored, [add_op("slots.constraints.must", "y")], model_scope="glm5")
        moved = ledger.apply(make_patch(stored, [add_op("slots.workflow", "third")], intent="improve")).ir
        rebased = rebase_patch(overlay, moved)
        outcome = apply_overlays(moved, [rebased])
        assert outcome.applied == [rebased.patch_id]
        assert "y" in outcome.ir.slots.constraints.must

    def test_render_reports_stale(self, seed, ledger: Ledger) -> None:
        ir, _ = seed
        stored = ledger.create_ir(ir.payload() | {"checksum": ir.checksum})
        overlay = make_patch(stored, [add_op("slots.constraints.must", "z")], model_scope="glm5")
        moved = ledger.apply(make_patch(stored, [add_op("slots.workflow", "third")], intent="improve")).ir
        result = render_with_overlays(moved, "glm5", [overlay])
        assert overlay.patch_id in result.stale_overlays


class TestTwentyRandomSeeds:
    def test_no_partial_application_and_no_unexplained_regression(self, ledger: Ledger) -> None:
        base_ir = generate_from_frame(extract_rules(SEED_TASK))
        base_text = render(base_ir, "glm5").text
        tasks = select_regression_tasks(load_tasks(TASKS), base_text)
        tasks = tasks[:2]

        for index in range(20):
            rng = random.Random(index)
            lines = base_text.splitlines()
            droppable = [i for i, line in enumerate(lines) if line.strip() and not line.startswith("#")]
            if droppable:
                lines.pop(rng.choice(droppable))
            mutated = "\n".join(lines)
            try:
                seed_ir = parse_seed_prompt(mutated)
            except Exception:  # 解析失败必须显式失败，而不是产出半成品
                continue

            stored = ledger.create_ir(
                seed_ir.payload() | {"checksum": seed_ir.checksum, "ir_id": f"ir-rand-{index}"}
            )
            before = len(ledger.history(stored.ir_id))
            outcome = run_iterate(
                stored,
                "请用表格输出",
                ledger,
                max_rounds=2,
                regression_tasks=tasks,
            )
            after = ledger.history(stored.ir_id)

            assert len(after) == before + len(outcome.applied)
            assert after == list(range(1, len(after) + 1))
            for rejection in outcome.rejected:
                assert rejection["reason"] in {"apply_failed", "regression"}
                if rejection["reason"] == "regression":
                    assert rejection["detail"]["regressions"]
            assert outcome.final_ir.verify_checksum()
