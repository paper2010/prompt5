"""M2 · 从零生成闭环测试：抽取（LLM/规则/回退）、生成、渲染、L1、CLI。"""

from __future__ import annotations

import json

import pytest

from prompt5.cli import main
from prompt5.engine.flow_zero import run_zero
from prompt5.ir import IR
from prompt5.llm.client import MockLLM
from prompt5.modules.m1_extractor import extract_intent, extract_rules
from prompt5.modules.m3_cards import card_hash, render
from prompt5.modules.m4_generator import generate_from_frame
from prompt5.modules.m5_eval.l1_rules import check, estimate_tokens

TASK = "把这份 CSV 做成分析报告"


class TestExtractor:
    def test_rules_analysis(self) -> None:
        frame = extract_rules(TASK)
        assert frame.task_type == "analysis"
        assert frame.slots["goal"]["outcome"] == TASK
        assert "分析报告" in frame.slots["output"]["format"]
        assert any("不得编造" in item for item in frame.slots["constraints"]["must_not"])
        assert "inputs" in frame.missing

    def test_rules_other_task(self) -> None:
        frame = extract_rules("帮我想想办法")
        assert frame.task_type == "other"
        assert "output.format" in frame.missing

    def test_llm_merge(self) -> None:
        frame = extract_intent(TASK, llm=MockLLM())
        assert frame.source == "merged"
        assert frame.slots["goal"]["outcome"] == TASK
        assert frame.confidence["goal.outcome"] >= 0.9
        assert "inputs" in frame.missing  # 材料缺失不得被合并吞掉

    def test_llm_invalid_falls_back(self) -> None:
        frame = extract_intent(TASK, llm=MockLLM(fixed_response="not-json"))
        assert frame.source == "rules"
        assert any("回退规则抽取" in item for item in frame.assumptions)

    def test_llm_off_schema_falls_back(self) -> None:
        frame = extract_intent(TASK, llm=MockLLM(fixed_response=json.dumps({"task_type": "invalid"})))
        assert frame.source == "rules"

    def test_no_llm_is_rules(self) -> None:
        assert extract_intent(TASK).source == "rules"


class TestGenerator:
    def test_ir_is_valid(self) -> None:
        ir = generate_from_frame(extract_rules(TASK))
        assert isinstance(ir, IR)
        assert ir.verify_checksum()
        assert ir.created["strategy_id"] == "skeleton"
        assert ir.slots.role
        assert ir.slots.constraints.must
        assert ir.slots.feedback_protocol["on_fail_report"]

    def test_explicit_ids_are_used(self) -> None:
        ir = generate_from_frame(extract_rules(TASK), ir_id="ir-fixed", lineage_id="lin-fixed")
        assert ir.ir_id == "ir-fixed"
        assert ir.lineage_id == "lin-fixed"


class TestRender:
    def test_sections_present(self) -> None:
        ir = generate_from_frame(extract_rules(TASK))
        result = render(ir, "glm5")
        for heading in ("# 角色", "# 目标", "# 约束", "# 工作流", "# 输出格式", "# 失败反馈"):
            assert heading in result.text, heading
        assert "分析报告" in result.text

    def test_cache_key_deterministic(self) -> None:
        ir = generate_from_frame(extract_rules(TASK))
        assert render(ir, "glm5").cache_key == render(ir, "glm5").cache_key
        assert render(ir, "glm5").cache_key != render(ir, "generic").cache_key

    def test_cache_key_changes_with_ir(self) -> None:
        first = generate_from_frame(extract_rules(TASK))
        second = generate_from_frame(extract_rules("把这份 CSV 做成分析报告（含图表）"))
        assert render(first, "glm5").cache_key != render(second, "glm5").cache_key

    def test_unknown_card_rejected(self) -> None:
        ir = generate_from_frame(extract_rules(TASK))
        with pytest.raises(KeyError):
            render(ir, "no-such-model")

    def test_manifest_matches_sections(self) -> None:
        ir = generate_from_frame(extract_rules(TASK))
        result = render(ir, "glm5")
        assert len(result.instruction_manifest) >= 5
        assert all(item["section"] and item["body"] for item in result.instruction_manifest)

    def test_empty_sections_omitted(self) -> None:
        ir = generate_from_frame(extract_rules(TASK))
        result = render(ir, "glm5")
        assert "# 示例" not in result.text
        assert "# 输入" not in result.text


class TestL1:
    def test_passes_for_generated(self) -> None:
        ir = generate_from_frame(extract_rules(TASK))
        report = check(ir, render(ir, "glm5").text)
        assert report.passed is True
        assert report.score == 1.0
        assert report.token_estimate > 0

    def test_detects_missing_outcome(self) -> None:
        ir = generate_from_frame(extract_rules(TASK))
        data = ir.model_dump(mode="json", by_alias=True)
        data["slots"]["goal"]["outcome"] = ""
        from prompt5.ir import compute_checksum

        data["checksum"] = compute_checksum({k: v for k, v in data.items() if k != "checksum"})
        report = check(IR.model_validate(data), "x")
        assert report.passed is False
        assert any(f.code == "L1_GOAL_EMPTY" for f in report.findings)

    def test_detects_contradiction(self) -> None:
        frame = extract_rules(TASK)
        frame.slots["constraints"]["must_not"] = list(frame.slots["constraints"]["must"])
        ir = generate_from_frame(frame)
        report = check(ir, render(ir, "glm5").text)
        assert any(f.code == "L1_CONTRADICTION" for f in report.findings)
        assert report.passed is False

    def test_detects_empty_item(self) -> None:
        frame = extract_rules(TASK)
        frame.slots["constraints"]["must"].append("  ")
        ir = generate_from_frame(frame)
        report = check(ir, "")
        assert any(f.code == "L1_EMPTY_ITEM" for f in report.findings)

    def test_token_budget_warning(self) -> None:
        ir = generate_from_frame(extract_rules(TASK))
        report = check(ir, "字" * 9000, token_budget=1000)
        assert any(f.code == "L1_TOKEN_BUDGET" for f in report.findings)
        assert report.passed is True  # 仅告警

    def test_protect_loc_unresolved(self) -> None:
        ir = generate_from_frame(extract_rules(TASK))
        data = ir.model_dump(mode="json", by_alias=True)
        data["protect_registry"] = [
            {"loc": "slots.constraints.must[c-zzzz99]", "cls": "safety", "state": "enacted"}
        ]
        from prompt5.ir import IR as IRModel, compute_checksum

        data["checksum"] = compute_checksum({k: v for k, v in data.items() if k != "checksum"})
        report = check(IRModel.model_validate(data), "")
        assert any(f.code == "L1_PROTECT_LOC_UNRESOLVED" for f in report.findings)


class TestFlowZero:
    def test_end_to_end(self) -> None:
        result = run_zero(TASK, llm=MockLLM(), ir_id="ir-e2e")
        assert result.ok is True
        assert result.ir.ir_id == "ir-e2e"
        assert result.rendered.model_id == "glm5"
        assert "分析报告" in result.rendered.text
        assert result.l1.passed
        assert result.frame.source == "merged"

    def test_works_without_llm(self) -> None:
        result = run_zero(TASK)
        assert result.frame.source == "rules"
        assert result.ok

    def test_estimate_tokens(self) -> None:
        assert estimate_tokens("中文四个字") >= 4
        assert estimate_tokens("abcdefgh") == 2


class TestCli:
    def test_demo_zero(self, capsys) -> None:
        code = main(["demo-zero", "--task", TASK, "--ir-id", "ir-cli"])
        out = capsys.readouterr().out
        assert code == 0
        for marker in ("========== IntentFrame ==========", "========== IR ==========",
                       "========== Rendered (glm5) ==========", "========== L1 Report =========="):
            assert marker in out, marker
        assert "ir-cli" in out
        assert "分析报告" in out
        assert "passed=True" in out

    def test_demo_zero_json(self, capsys) -> None:
        main(["demo-zero", "--task", TASK, "--json"])
        out = capsys.readouterr().out
        assert '"schema_version": "3"' in out
        assert '"strategy_id": "skeleton"' in out

    def test_extract_subcommand(self, capsys) -> None:
        main(["extract", "--task", TASK])
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["task_type"] == "analysis"
