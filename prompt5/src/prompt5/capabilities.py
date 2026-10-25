"""能力目录与错误码总表（唯一数据源，API / TCK / 文档均从此读取）。

来源：《搭建执行方案》§4.5（错误码）与 §10.1（资源）、§6.2 能力目录。
计数纪律：MCP 工具共 18 个；能力共 9 项；任何"13 工具"表述均已作废（D-5）。
"""

from __future__ import annotations

__all__ = ["CAPABILITIES", "ERROR_CODES", "MCP_TOOLS", "capability_ids"]

# 9 项能力：op → 元数据（同步性 / 就绪阶段 / 所需 scope）
CAPABILITIES: dict[str, dict] = {
    "discovery.v1": {"sync": True, "ready": "P0a", "scope": "discovery.v1"},
    "generate.v1": {"sync": False, "ready": "P0a", "scope": "generate.v1"},
    "render.v1": {"sync": True, "ready": "P0a", "scope": "render.v1"},
    "score.v1": {"sync": "mixed", "ready": "P0a", "scope": "score.v1"},
    "iterate.v1": {"sync": False, "ready": "P0b", "scope": "iterate.v1"},
    "protection.request.v1": {"sync": True, "ready": "P0b", "scope": "protection.request.v1"},
    "modelcard.request.v1": {"sync": True, "ready": "P0b", "scope": "modelcard.request.v1"},
    "events.v1": {"sync": False, "ready": "P1", "scope": "events.v1"},
    "governance.read.v1": {"sync": True, "ready": "P1", "scope": "governance.read.v1"},
}

# 18 个 MCP 工具 → 所属能力（TCK 按此矩阵逐格断言）
MCP_TOOLS: dict[str, str] = {
    "pg_capabilities": "discovery.v1",
    "pg_schema_get": "discovery.v1",
    "pg_model_cards": "discovery.v1",
    "pg_generate": "generate.v1",
    "pg_iterate": "iterate.v1",
    "pg_task_status": "generate.v1",
    "pg_task_cancel": "generate.v1",
    "pg_rubric_confirm": "generate.v1",
    "pg_evidence_get": "governance.read.v1",
    "pg_score": "score.v1",
    "pg_render": "render.v1",
    "pg_session_open": "events.v1",
    "pg_turn_record": "events.v1",
    "pg_patch_apply": "events.v1",
    "pg_session_status": "governance.read.v1",
    "pg_budget_read": "governance.read.v1",
    "pg_protection_request": "protection.request.v1",
    "pg_modelcard_request": "modelcard.request.v1",
}

# 错误码 → HTTP 状态（E_IDEM_REPLAY 为响应元数据，非错误）
ERROR_CODES: dict[str, int] = {
    # core（应用器 / 引擎）
    "E_BASE_DRIFT": 409,
    "E_SCHEMA_INVALID": 422,
    "E_INDEX_FORBIDDEN": 422,
    "E_ROOT_FORBIDDEN": 422,
    "E_ID_SYNTAX": 422,
    "E_FIELD_UNKNOWN": 422,
    "E_LOC_RETIRED": 422,
    "E_ADD_TARGET": 422,
    "E_DELETE_TARGET": 422,
    "E_DELETE_NONEMPTY": 422,
    "E_REWRITE_TARGET": 422,
    "E_MOVE_TARGET": 422,
    "E_MOVE_ANCHOR": 422,
    "E_PROTECT_ENACTED": 403,
    "E_PROTECT_REWRITE": 403,
    "E_PROTECT_MOVE": 403,
    "E_PROTECT_ANCESTOR": 403,
    "E_PROTECT_FIELD": 403,
    "E_PROTECT_CONSUMED": 409,
    "E_INTENT_MISMATCH": 422,
    "E_FENCING_STALE": 409,
    "E_IDEM_REPLAY": 200,
    # transport（API 层）
    "E_AUTH": 401,
    "E_AUTH_IDENTITY_MISMATCH": 401,
    "E_SCOPE": 403,
    "E_RATE_LIMIT": 429,
    "E_BUDGET_EXCEEDED": 429,
    "E_UNSUPPORTED_OP": 501,
    "E_EVENT_ORDER": 422,
    "E_BLOB_TOO_LARGE": 413,
    "E_BLOB_MIME": 415,
    "E_BLOB_QUOTA": 429,
}


def capability_ids() -> list[str]:
    return list(CAPABILITIES.keys())
