"""MCP 绑定：18 个工具的注册表与调度（与 HTTP 共用 ConnectorService）。"""

from __future__ import annotations

from typing import Any

from ..capabilities import MCP_TOOLS
from .api import Context, ConnectorService, ServiceError

__all__ = ["TOOL_SPECS", "list_tools", "call_tool"]

_DESCRIPTIONS = {
    "pg_capabilities": "能力协商（含 scope 状态）",
    "pg_schema_get": "获取 IR/Patch/TaskRequest/EvalEvidence 的 JSON Schema",
    "pg_model_cards": "受支持目标模型清单（含 tier/label/primary）",
    "pg_generate": "从零生成任务（异步语义，返回 task_id）",
    "pg_iterate": "种子提示词迭代（同步返回最终 IR）",
    "pg_task_status": "查询任务状态与结果",
    "pg_task_cancel": "取消任务（终态不可取消）",
    "pg_rubric_confirm": "确认 rubric（人工锚点）",
    "pg_evidence_get": "读取评测证据（含复现层级）",
    "pg_score": "L1 静态评分",
    "pg_render": "按模型卡渲染 IR",
    "pg_session_open": "开启在线会话",
    "pg_turn_record": "记录对话轮（语义门控）",
    "pg_patch_apply": "按 suggestion_id 应用建议补丁",
    "pg_session_status": "查询会话状态",
    "pg_budget_read": "读取预算上限与用量",
    "pg_protection_request": "提交保护类建议（不批准）",
    "pg_modelcard_request": "提交新模型卡申请（不直写）",
}

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": name,
        "description": _DESCRIPTIONS.get(name, ""),
        "capability": capability,
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": True},
    }
    for name, capability in MCP_TOOLS.items()
]


def list_tools() -> list[dict[str, Any]]:
    return TOOL_SPECS


def call_tool(name: str, args: dict[str, Any], service: ConnectorService,
              ctx: Context) -> dict[str, Any]:
    if name == "pg_capabilities":
        return service.capabilities(ctx)
    if name == "pg_schema_get":
        return service.schemas(ctx)
    if name == "pg_model_cards":
        return service.model_cards(ctx)
    if name == "pg_generate":
        _, body, _ = service.create_task(ctx, args)
        return body
    if name == "pg_iterate":
        return service.iterate(ctx, args)
    if name == "pg_task_status":
        return service.get_task(ctx, str(args.get("task_id", "")))
    if name == "pg_task_cancel":
        return service.cancel_task(ctx, str(args.get("task_id", "")))
    if name == "pg_rubric_confirm":
        return service.confirm_rubric(ctx, str(args.get("task_id", "")))
    if name == "pg_evidence_get":
        return service.evidence(ctx, str(args.get("task_id", "")))
    if name == "pg_score":
        return service.score(ctx, args)
    if name == "pg_render":
        return service.render(ctx, args)
    if name == "pg_session_open":
        return service.open_session(ctx, args)
    if name == "pg_turn_record":
        return service.record_turn(ctx, str(args.get("session_id", "")), args)
    if name == "pg_patch_apply":
        return service.apply_patch(ctx, str(args.get("session_id", "")), args)
    if name == "pg_session_status":
        return service.get_session(ctx, str(args.get("session_id", "")))
    if name == "pg_budget_read":
        return service.budget(ctx)
    if name == "pg_protection_request":
        return service.request_protection(ctx, args)
    if name == "pg_modelcard_request":
        return service.request_model_card(ctx, args)
    raise ServiceError("E_UNSUPPORTED_OP", 501, f"unknown tool {name!r}")
