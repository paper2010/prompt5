"""LLM 客户端抽象：OpenAI 兼容 + 确定性 Mock（离线/测试用）。

约定（执行方案 §8.1）：所有模块只依赖 `LLMClient` 协议；供应商故障 fail-closed，
禁止自动切换模型；调用方负责超时重试策略（默认 ≤1 次）。
"""

from __future__ import annotations

import json
from typing import Any, Protocol, Sequence

__all__ = ["LLMClient", "LLMError", "MockLLM", "OpenAICompatLLM", "message"]


class LLMError(RuntimeError):
    """调用失败（网络/协议/超时）；上层按 fail-closed 处理。"""


class LLMClient(Protocol):
    name: str

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str: ...


def message(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


class MockLLM:
    """确定性 Mock：输出只依赖输入文本，供 M2/M3 离线闭环与测试使用。

    支持的提示词标记：
      <<INTENT_EXTRACT>>  → 返回最小合法 IntentFrame JSON（含任务原文）
    其他输入 → 原样回显（便于断言调用链）。
    """

    name = "mock"

    def __init__(self, *, fixed_response: str | None = None) -> None:
        self.calls: list[list[dict[str, str]]] = []
        self.fixed_response = fixed_response

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        self.calls.append([dict(m) for m in messages])
        if self.fixed_response is not None:
            return self.fixed_response

        last = messages[-1]["content"] if messages else ""
        if "<<INTENT_EXTRACT>>" in last:
            return json.dumps(self._intent_payload(last), ensure_ascii=False)
        return f"[mock-echo] {last[:80]}"

    @staticmethod
    def _intent_payload(prompt: str) -> dict[str, Any]:
        task = ""
        for line in prompt.splitlines():
            if line.startswith("TASK:"):
                task = line[len("TASK:") :].strip()
                break
        lowered = task.lower()
        if any(key in task for key in ("报告", "分析", "数据")) or "csv" in lowered:
            task_type, fmt = "analysis", "分析报告（结论、要点、数据依据）"
        elif any(key in task for key in ("整理", "转换", "格式")):
            task_type, fmt = "transform", "结构化清单"
        elif any(key in task for key in ("写", "文案", "邮件", "文案")):
            task_type, fmt = "draft", "成稿文本"
        elif any(key in task for key in ("代码", "脚本", "重构")):
            task_type, fmt = "code", "可运行代码 + 说明"
        else:
            task_type, fmt = "other", "文本"
        return {
            "task_type": task_type,
            "slots": {"goal": {"outcome": task}, "output": {"format": fmt}},
            "confidence": {"goal.outcome": 0.92, "output.format": 0.78},
        }


class OpenAICompatLLM:  # pragma: no cover - 需真实端点
    """OpenAI 兼容 Chat Completions；`response_format=json_schema` 透传结构化输出。"""

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str = "",
        timeout: float = 120.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.name = model
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.headers = dict(headers or {})

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        import httpx

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "payload", "strict": True, "schema": json_schema},
            }
        headers = {"Content-Type": "application/json", **self.headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except Exception as exc:  # 网络/HTTP 一律 fail-closed
            raise LLMError(f"llm call failed: {exc}") from exc
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"unexpected response shape: {data}") from exc
