"""L2 表达评估：交换顺序双裁 + 一致性处理 + 单次重裁。

规则（执行方案 §5.3）：
- 同一对提示词按 A/B 与 B/A 各裁一次；两次结论一致才计为胜/负；
- 不一致 → 重裁一次；仍不一致 → 记平局（允许非传递，不强行排序）；
- rubric 必须由调用方提供（来自已确认的意图框架），裁判不得自行发挥。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol, Sequence

from ...llm.client import LLMClient, LLMError, message

__all__ = ["Judgement", "PairwiseJudge", "LLMJudge", "MockJudge", "judge_pair"]

JUDGE_SYSTEM_PROMPT = (
    "你是严格的提示词评审。依据给定 rubric 比较两个提示词，只输出 JSON："
    '{"winner":"A|B|tie","rationale":"一句话"}。'
    "不要臆测模型能力，不要引入 rubric 之外的偏好。"
)


@dataclass
class Judgement:
    winner: str  # "a" | "b" | "tie"
    consistent: bool
    calls: int
    rationale: str = ""
    details: list[dict] = field(default_factory=list)

    @property
    def decided(self) -> bool:
        return self.winner in {"a", "b"}


class PairwiseJudge(Protocol):
    def verdict(self, first: str, second: str, rubric: Sequence[str]) -> str:  # "a"|"b"|"tie"
        ...


class LLMJudge:
    """基于 LLM 的成对裁判；解析失败按平局处理（fail-closed，不放大噪声）。"""

    def __init__(self, client: LLMClient, *, model_snapshot: str | None = None, prompt_version: str = "rubric-v1") -> None:
        self.client = client
        self.model_snapshot = model_snapshot or getattr(client, "name", "unknown")
        self.prompt_version = prompt_version

    def verdict(self, first: str, second: str, rubric: Sequence[str]) -> str:
        criteria = "\n".join(f"- {item}" for item in rubric)
        prompt = (
            f"# 评审标准\n{criteria}\n\n# 提示词 A\n{first}\n\n# 提示词 B\n{second}\n\n"
            "请判定哪一个更能满足上述标准（A / B / tie）。"
        )
        try:
            raw = self.client.chat(
                [message("system", JUDGE_SYSTEM_PROMPT), message("user", prompt)],
                json_schema={
                    "type": "object",
                    "properties": {
                        "winner": {"type": "string", "enum": ["A", "B", "tie"]},
                        "rationale": {"type": "string"},
                    },
                    "required": ["winner"],
                },
            )
            payload = json.loads(raw)
            winner = str(payload.get("winner", "tie")).strip().lower()
            return winner if winner in {"a", "b", "tie"} else "tie"
        except (LLMError, json.JSONDecodeError, ValueError, TypeError):
            return "tie"


class MockJudge:
    """离线裁判：按 rubric 关键词命中数打分，确定性可断言。"""

    def __init__(self) -> None:
        self.name = "mock-judge"
        self.calls = 0

    def verdict(self, first: str, second: str, rubric: Sequence[str]) -> str:
        self.calls += 1

        def score(text: str) -> int:
            return sum(1 for item in rubric if item.split("：")[0].split(":")[0][:6] in text)

        left, right = score(first), score(second)
        if left == right:
            return "tie"
        return "a" if left > right else "b"


def judge_pair(
    judge: PairwiseJudge,
    first: str,
    second: str,
    rubric: Sequence[str],
    *,
    allow_retry: bool = True,
) -> Judgement:
    """交换顺序双裁；不一致时重裁一次，仍不一致记平局。"""
    forward = judge.verdict(first, second, rubric)
    backward_raw = judge.verdict(second, first, rubric)
    backward = {"a": "b", "b": "a", "tie": "tie"}[backward_raw]
    calls = 2
    details = [{"order": "ab", "verdict": forward}, {"order": "ba", "verdict": backward_raw}]

    if forward == backward:
        return Judgement(winner=forward, consistent=True, calls=calls, details=details)

    if not allow_retry:
        return Judgement(winner="tie", consistent=False, calls=calls, details=details)

    third = judge.verdict(first, second, rubric)
    calls += 1
    details.append({"order": "ab-retry", "verdict": third})
    if third == forward or third == backward:
        winner = third
        return Judgement(winner=winner, consistent=False, calls=calls, details=details)
    return Judgement(winner="tie", consistent=False, calls=calls, details=details)
