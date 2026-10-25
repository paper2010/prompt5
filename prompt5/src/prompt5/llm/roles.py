"""角色 → LLM 客户端：从配置解析供应商端点/密钥并实例化。

生效链路：config.yaml → load_config（${ENV} 展开）→ resolve_role（端点/密钥校验）
         → OpenAICompatLLM（base_url + api_key + headers + timeout）→ 模块调用。
"""

from __future__ import annotations

from typing import Any

from ..config import ConfigError, RoleBinding, resolve_role
from .client import LLMClient, MockLLM, OpenAICompatLLM

__all__ = ["ROLE_NAMES", "build_llm", "describe_roles"]

ROLE_NAMES = ("generator", "judge_glm", "judge_dsk", "judge_qwen", "reflector")


def build_llm(role: str, data: dict[str, Any], *, mock: bool = False) -> LLMClient:
    """按角色构造客户端；mock=True 时返回确定性 Mock（离线）。"""
    if mock:
        return MockLLM()
    binding: RoleBinding = resolve_role(data, role)
    if binding.provider.api_style != "openai":
        raise ConfigError(f"provider {binding.provider.name!r} 的 api_style 暂不支持")
    return OpenAICompatLLM(
        model=binding.model,
        base_url=binding.provider.base_url,
        api_key=binding.provider.api_key,
        timeout=binding.provider.timeout,
        headers=binding.provider.headers,
    )


def describe_roles(data: dict[str, Any]) -> list[dict[str, Any]]:
    """列出角色绑定（含端点，密钥只显示是否已配置），供 `config check` 展示。"""
    rows: list[dict[str, Any]] = []
    for role in (data.get("roles") or {}):
        row: dict[str, Any] = {"role": role}
        try:
            binding = resolve_role(data, role)
            row.update(
                {
                    "provider": binding.provider.name,
                    "model": binding.model,
                    "base_url": binding.provider.base_url,
                    "api_key": "已配置" if binding.provider.api_key else "未配置",
                    "timeout": binding.provider.timeout,
                    "status": "ok",
                }
            )
        except ConfigError as exc:
            row.update({"status": "error", "error": str(exc)})
        rows.append(row)
    return rows
