"""L1 静态规则引擎：零调用、可解释、快速淘汰。

契约：执行方案 §5.1 证据层级 —— L1 只能证明「结构合法/无矛盾/合预算」，不得宣称质量。
检查项：槽位完整性、must/must_not 矛盾、空条目、token 预算、保护类 loc 可解析性。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...ir import IR
from ...patch import LocError, classify_loc

__all__ = ["Finding", "L1Report", "check", "estimate_tokens"]

_SEVERITY_WEIGHT = {"error": 0.1, "warn": 0.03}


@dataclass
class Finding:
    code: str
    severity: str  # error | warn | info
    message: str
    loc: str = ""


@dataclass
class L1Report:
    passed: bool
    score: float
    findings: list[Finding] = field(default_factory=list)
    token_estimate: int = 0

    def by_severity(self, severity: str) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == severity]

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "score": round(self.score, 3),
            "token_estimate": self.token_estimate,
            "findings": [
                {"code": f.code, "severity": f.severity, "message": f.message, "loc": f.loc}
                for f in self.findings
            ],
        }


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：中日韩字符 ≈ 1 token/字，其余 ≈ 1 token/4 字符。

    仅用于预算预警（L1），不作计费依据；精确值以目标模型 tokenizer 为准。
    """
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return cjk + max(1, other // 4)


def check(ir: IR, rendered_text: str = "", *, token_budget: int = 4000) -> L1Report:
    findings: list[Finding] = []

    if not ir.verify_checksum():
        findings.append(Finding("L1_CHECKSUM_INVALID", "error", "IR checksum 不匹配", "checksum"))

    if not ir.slots.goal.outcome.strip():
        findings.append(Finding("L1_GOAL_EMPTY", "error", "goal.outcome 为空", "slots.goal.outcome"))
    if not ir.slots.output.format.strip():
        findings.append(Finding("L1_FORMAT_EMPTY", "error", "output.format 为空", "slots.output.format"))
    if not ir.slots.goal.done_criteria:
        findings.append(
            Finding("L1_NO_DONE_CRITERIA", "error", "缺少完成标准", "slots.goal.done_criteria")
        )
    if not ir.slots.constraints.must and not ir.slots.constraints.must_not:
        findings.append(Finding("L1_NO_CONSTRAINTS", "warn", "没有任何约束", "slots.constraints"))
    if not ir.slots.workflow:
        findings.append(Finding("L1_NO_WORKFLOW", "warn", "缺少工作流", "slots.workflow"))
    if not ir.slots.feedback_protocol.get("on_fail_report"):
        findings.append(
            Finding(
                "L1_NO_FEEDBACK_PROTOCOL",
                "warn",
                "缺少失败反馈协议（现象/复现/已尝试/影响面）",
                "slots.feedback_protocol",
            )
        )

    must_normalized = {item.strip().rstrip("。；;") for item in ir.slots.constraints.must}
    for item in ir.slots.constraints.must_not:
        if item.strip().rstrip("。；;") in must_normalized:
            findings.append(
                Finding(
                    "L1_CONTRADICTION",
                    "error",
                    f"同一内容同时出现在 must 与 must_not：{item!r}",
                    "slots.constraints",
                )
            )

    for path, values in (
        ("slots.constraints.must", ir.slots.constraints.must),
        ("slots.constraints.must_not", ir.slots.constraints.must_not),
        ("slots.constraints.style", ir.slots.constraints.style),
        ("slots.workflow", ir.slots.workflow),
        ("slots.goal.done_criteria", ir.slots.goal.done_criteria),
    ):
        for index, value in enumerate(values):
            if not str(value).strip():
                findings.append(
                    Finding("L1_EMPTY_ITEM", "error", f"第 {index + 1} 项为空", f"{path}[{index}]")
                )

    for entry in ir.protect_registry:
        try:
            target = classify_loc(entry.loc)
        except LocError as exc:
            findings.append(
                Finding("L1_PROTECT_LOC_INVALID", "error", f"保护类 loc 非法：{exc.code}", entry.loc)
            )
            continue
        if target.item_id and target.item_id not in ir.item_ids.get(target.path, []):
            findings.append(
                Finding("L1_PROTECT_LOC_UNRESOLVED", "error", "保护类 loc 指向不存在的条目", entry.loc)
            )
        if entry.state == "proposed":
            findings.append(
                Finding("L1_PROTECT_PROPOSED", "warn", "存在待批准的保护类注册", entry.loc)
            )

    token_estimate = estimate_tokens(rendered_text) if rendered_text else 0
    if token_estimate > token_budget:
        findings.append(
            Finding(
                "L1_TOKEN_BUDGET",
                "warn",
                f"渲染文本约 {token_estimate} tokens，超出预算 {token_budget}",
                "rendered",
            )
        )

    errors = sum(1 for finding in findings if finding.severity == "error")
    warns = sum(1 for finding in findings if finding.severity == "warn")
    score = max(0.0, 1.0 - errors * _SEVERITY_WEIGHT["error"] - warns * _SEVERITY_WEIGHT["warn"])
    return L1Report(
        passed=errors == 0,
        score=score,
        findings=findings,
        token_estimate=token_estimate,
    )
