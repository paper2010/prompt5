"""M3 模型适配：模型卡 + 渲染器（IR → 目标模型风格文本）。

M2 只实现 glm5 一张卡（markdown 结构）；overlay 管线在 M4 接入。
缓存键复用执行方案 §6.1：ir_checksum + overlay + card_hash + renderer + template + decode。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..canonical import sha256_hex, tuple_hash
from ..ir import IR

__all__ = [
    "CARDS",
    "RENDERER_VERSION",
    "TEMPLATE_VERSION",
    "RenderResult",
    "card_hash",
    "get_card",
    "render",
]

RENDERER_VERSION = "rc1"
TEMPLATE_VERSION = "tpl1"

CARDS: dict[str, dict[str, Any]] = {
    "glm5": {
        "model_id": "glm5",
        "display": "GLM-5",
        "structure": "markdown",
        "prefer": ["分点指令", "显式输出格式", "首尾重申关键约束"],
        "max_sections": 8,
    },
    "deepseek": {
        "model_id": "deepseek",
        "display": "DeepSeek",
        "structure": "markdown",
        "prefer": ["显式约束清单", "结论先行", "分点指令"],
        "max_sections": 8,
    },
    "zhipu": {
        "model_id": "zhipu",
        "display": "智谱 GLM",
        "structure": "markdown",
        "prefer": ["分节标题", "显式输出格式"],
        "max_sections": 8,
    },
    "kimi": {
        "model_id": "kimi",
        "display": "Moonshot Kimi",
        "structure": "markdown",
        "prefer": ["长文分节", "逐条约束"],
        "max_sections": 8,
    },
    "minimax": {
        "model_id": "minimax",
        "display": "MiniMax",
        "structure": "markdown",
        "prefer": ["结论先行", "步骤化"],
        "max_sections": 8,
    },
    "mimo": {
        "model_id": "mimo",
        "display": "小米 MiMo",
        "structure": "markdown",
        "prefer": ["简洁指令", "显式格式"],
        "max_sections": 8,
    },
    "generic": {
        "model_id": "generic",
        "display": "Generic",
        "structure": "markdown",
        "prefer": [],
        "max_sections": 8,
    },
}


@dataclass
class RenderResult:
    text: str
    cache_key: str
    model_id: str
    card_hash: str
    instruction_manifest: list[dict[str, str]] = field(default_factory=list)
    stale_overlays: list[str] = field(default_factory=list)


def get_card(model_id: str) -> dict[str, Any]:
    if model_id not in CARDS:
        raise KeyError(f"unknown model card {model_id!r}")
    return CARDS[model_id]


def card_hash(model_id: str) -> str:
    return sha256_hex(get_card(model_id))


def _bullets(items: list[str], bullet: str = "- ") -> str:
    return "\n".join(f"{bullet}{item}" for item in items if item.strip())


def _numbered(items: list[str]) -> str:
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1) if item.strip())


def _sections(ir: IR, card: dict[str, Any]) -> list[tuple[str, str]]:
    slots = ir.slots
    sections: list[tuple[str, str]] = []

    role = slots.role.strip()
    if role:
        sections.append(("角色", f"你是{role}。"))

    goal_parts = [slots.goal.outcome.strip()] if slots.goal.outcome.strip() else []
    if slots.goal.done_criteria:
        goal_parts.append("完成标准：\n" + _bullets(slots.goal.done_criteria))
    if slots.goal.non_goals:
        goal_parts.append("明确不做：\n" + _bullets(slots.goal.non_goals))
    if goal_parts:
        sections.append(("目标", "\n\n".join(goal_parts)))

    if slots.inputs:
        sections.append(
            ("输入", _bullets([f"{item.ref}（{item.type}）{item.note}".strip() for item in slots.inputs]))
        )

    constraint_parts: list[str] = []
    if slots.constraints.must:
        constraint_parts.append("必须：\n" + _numbered(slots.constraints.must))
    if slots.constraints.must_not:
        constraint_parts.append("禁止：\n" + _bullets(slots.constraints.must_not))
    if slots.constraints.style:
        constraint_parts.append("风格：\n" + _bullets(slots.constraints.style))
    if constraint_parts:
        sections.append(("约束", "\n\n".join(constraint_parts)))

    if slots.workflow:
        sections.append(("工作流", _numbered(slots.workflow)))

    output_lines = [f"格式：{slots.output.format}"]
    if slots.output.length_budget:
        output_lines.append(f"长度：{slots.output.length_budget}")
    if slots.output.output_schema:
        output_lines.append("结构约束：" + str(slots.output.output_schema))
    sections.append(("输出格式", "\n".join(output_lines)))

    if slots.examples:
        blocks = [
            f"输入：{example.input}\n期望输出：{example.expected}" for example in slots.examples
        ]
        sections.append(("示例", "\n\n".join(blocks)))

    protocol = slots.feedback_protocol.get("on_fail_report") if slots.feedback_protocol else None
    if protocol:
        sections.append(("失败反馈", f"若无法完成，按以下格式报告：{protocol}"))

    for extra in ir.freeform_extras:
        if extra.text.strip():
            sections.append((f"补充：{extra.note or extra.id[:8]}", extra.text.strip()))

    return sections[: int(card.get("max_sections", 8))]


def render(
    ir: IR,
    model_id: str = "glm5",
    *,
    decode: dict[str, Any] | None = None,
    overlays: list[str] | None = None,
    stale_overlays: list[str] | None = None,
) -> RenderResult:
    card = get_card(model_id)
    sections = _sections(ir, card)
    text = "\n\n".join(f"# {title}\n{body}" for title, body in sections) + "\n"
    payload_overlays = list(overlays or [])
    key = tuple_hash(
        [
            ("ir", ir.checksum),
            ("overlay", sha256_hex(payload_overlays) if payload_overlays else "none"),
            ("card", card_hash(model_id)),
            ("renderer", RENDERER_VERSION),
            ("template", TEMPLATE_VERSION),
            ("decode", sha256_hex(decode or {})),
        ]
    )
    manifest = [{"section": title, "body": body} for title, body in sections]
    return RenderResult(
        text=text,
        cache_key=key,
        model_id=model_id,
        card_hash=card_hash(model_id),
        instruction_manifest=manifest,
        stale_overlays=list(stale_overlays or []),
    )
