"""M3 · L2 交换双裁测试：一致性、重裁、平局、LLM 解析失败 fail-closed。"""

from __future__ import annotations

import json

from prompt5.llm.client import MockLLM
from prompt5.modules.m5_eval.l2_judge import LLMJudge, MockJudge, judge_pair

RUBRIC = ["输出格式：明确指出交付物格式", "完成标准：可判定", "失败反馈：给出定位线索"]


class _ScriptedJudge:
    def __init__(self, sequence: list[str]) -> None:
        self.sequence = sequence
        self.calls = 0

    def verdict(self, first: str, second: str, rubric) -> str:  # noqa: ANN001
        value = self.sequence[self.calls]
        self.calls += 1
        return value


class TestMockJudge:
    def test_richer_prompt_wins(self) -> None:
        judge = MockJudge()
        first = "输出格式：markdown；完成标准：清单；失败反馈：现象"
        second = "随便写"
        assert judge.verdict(first, second, RUBRIC) == "a"
        assert judge.verdict(second, first, RUBRIC) == "b"

    def test_tie_on_equal(self) -> None:
        judge = MockJudge()
        assert judge.verdict("同文", "同文", RUBRIC) == "tie"


class TestJudgePair:
    def test_consistent_winner(self) -> None:
        judgement = judge_pair(_ScriptedJudge(["a", "b"]), "A", "B", RUBRIC)
        assert judgement.winner == "a"
        assert judgement.consistent is True
        assert judgement.calls == 2

    def test_consistent_second_winner(self) -> None:
        judgement = judge_pair(_ScriptedJudge(["b", "a"]), "A", "B", RUBRIC)
        assert judgement.winner == "b"
        assert judgement.consistent is True

    def test_disagreement_retry_resolves(self) -> None:
        # 前向 a；反向 a（映射为 b）→ 不一致；重裁 b → 采信 b
        judgement = judge_pair(_ScriptedJudge(["a", "a", "b"]), "A", "B", RUBRIC)
        assert judgement.winner == "b"
        assert judgement.consistent is False
        assert judgement.calls == 3

    def test_disagreement_all_different_is_tie(self) -> None:
        judgement = judge_pair(_ScriptedJudge(["a", "a", "tie"]), "A", "B", RUBRIC)
        assert judgement.winner == "tie"
        assert judgement.decided is False

    def test_retry_disabled_gives_tie(self) -> None:
        judgement = judge_pair(_ScriptedJudge(["a", "a"]), "A", "B", RUBRIC, allow_retry=False)
        assert judgement.winner == "tie"
        assert judgement.calls == 2


class TestLLMJudge:
    def test_parses_verdict(self) -> None:
        client = MockLLM(fixed_response=json.dumps({"winner": "A", "rationale": "更完整"}))
        judge = LLMJudge(client)
        assert judge.verdict("p1", "p2", RUBRIC) == "a"

    def test_invalid_json_fails_closed(self) -> None:
        judge = LLMJudge(MockLLM(fixed_response="不是 JSON"))
        assert judge.verdict("p1", "p2", RUBRIC) == "tie"

    def test_unknown_winner_is_tie(self) -> None:
        judge = LLMJudge(MockLLM(fixed_response=json.dumps({"winner": "both"})))
        assert judge.verdict("p1", "p2", RUBRIC) == "tie"
