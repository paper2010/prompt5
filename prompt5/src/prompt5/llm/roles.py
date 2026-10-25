"""角色 / 裁判池 / 被测目标 → LLM 客户端（L2 裁判与 L3 执行端点均由配置开放）。

生效链路：
  config.yaml → load_config（${ENV} 展开）→ resolve_*（端点/密钥/回避规则校验）
  → OpenAICompatLLM（base_url + api_key + headers + timeout）→ 模块调用。
"""

from __future__ import annotations

from typing import Any

from ..config import (
    ConfigError,
    JudgeBinding,
    RoleBinding,
    primary_target,
    resolve_judge,
    resolve_provider,
    resolve_role,
    resolve_target,
)
from ..modules.m5_eval.l2_judge import LLMJudge
from .client import LLMClient, MockLLM, OpenAICompatLLM

__all__ = [
    "ROLE_NAMES",
    "build_llm",
    "build_generator",
    "build_judge",
    "build_target_client",
    "build_executor",
    "describe_roles",
    "describe_targets",
]

ROLE_NAMES = ("generator", "reflector")


def _client(provider, model: str) -> OpenAICompatLLM:
    if provider.api_style != "openai":
        raise ConfigError(f"provider {provider.name!r} 的 api_style 暂不支持")
    return OpenAICompatLLM(
        model=model,
        base_url=provider.base_url,
        api_key=provider.api_key,
        timeout=provider.timeout,
        headers=provider.headers,
    )


def build_llm(role: str, data: dict[str, Any], *, mock: bool = False) -> LLMClient:
    if mock:
        return MockLLM()
    binding: RoleBinding = resolve_role(data, role)
    return _client(binding.provider, binding.model)


def build_generator(data: dict[str, Any], *, mock: bool = False) -> LLMClient:
    return build_llm("generator", data, mock=mock)


def build_judge(data: dict[str, Any], target_provider: str) -> tuple[LLMJudge, dict[str, Any]]:
    """按回避规则为指定被测族挑选 L2 裁判（池由 roles.judges 提供）。"""
    binding: JudgeBinding = resolve_judge(data, target_provider)
    client = _client(binding.provider, binding.model)
    judge = LLMJudge(client, model_snapshot=f"{binding.provider.name}/{binding.model}")
    meta = {
        "role": binding.role,
        "family": binding.family,
        "provider": binding.provider.name,
        "model": binding.model,
        "base_url": binding.provider.base_url,
    }
    return judge, meta


def build_target_client(
    data: dict[str, Any], target_name: str | None = None
) -> tuple[LLMClient, dict[str, Any]]:
    name = target_name or primary_target(data)
    provider, model, raw = resolve_target(data, name)
    meta = {
        "target": name,
        "provider": provider.name,
        "model": model,
        "base_url": provider.base_url,
        "tier": raw.get("tier", ""),
        "label": raw.get("label", ""),
        "primary": bool(raw.get("primary")),
    }
    return _client(provider, model), meta


def build_executor(data: dict[str, Any], target_name: str | None = None):
    """构造 L3 真实执行器（OpenAI 兼容），供评测 / pilot 使用。"""
    from ..modules.m5_eval.l3_exec import OpenAICompatExecutor

    client, meta = build_target_client(data, target_name)
    return OpenAICompatExecutor(client, name=f"live:{meta['model']}"), meta


def describe_roles(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for role in ROLE_NAMES:
        if role not in (data.get("roles") or {}):
            continue
        try:
            binding = resolve_role(data, role)
            rows.append(
                {
                    "role": role,
                    "provider": binding.provider.name,
                    "model": binding.model,
                    "base_url": binding.provider.base_url,
                    "api_key": "已配置" if binding.provider.api_key else "未配置",
                    "status": "ok",
                }
            )
        except ConfigError as exc:
            rows.append({"role": role, "status": "error", "error": str(exc)})

    for entry in (data.get("roles") or {}).get("judges") or []:
        entry = entry or {}
        provider_name = str(entry.get("provider", ""))
        label = f"judge:{provider_name}"
        try:
            provider = resolve_provider(data, provider_name)
            model = str(entry.get("model", "")).strip()
            row = {
                "role": label,
                "provider": provider.name,
                "model": model,
                "base_url": provider.base_url,
                "api_key": "已配置" if provider.api_key else "未配置",
                "status": "ok" if model else "error",
            }
            if not model:
                row["error"] = "缺少 model"
            rows.append(row)
        except ConfigError as exc:
            rows.append({"role": label, "status": "error", "error": str(exc)})
    return rows


def describe_targets(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, raw in (data.get("targets") or {}).items():
        raw = raw or {}
        try:
            provider, model, _ = resolve_target(data, name)
            rows.append(
                {
                    "target": name,
                    "provider": provider.name,
                    "model": model,
                    "base_url": provider.base_url,
                    "primary": bool(raw.get("primary")),
                    "label": raw.get("label", ""),
                    "status": "ok",
                }
            )
        except ConfigError as exc:
            rows.append({"target": name, "status": "error", "error": str(exc)})
    return rows
