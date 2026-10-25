"""M3+ 配置生效链路：角色 → 供应商 → 客户端实例化（不发起网络请求）。"""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from prompt5.config import ConfigError, load_config
from prompt5.llm.client import MockLLM, OpenAICompatLLM
from prompt5.llm.roles import build_llm, describe_roles

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.example.yaml"
ENV = {
    "GLM_URL": "https://glm.example.com/v4",
    "DSK_URL": "https://dsk.example.com/v1",
    "QWEN_URL": "https://qwen.example.com/v1",
    "LOCAL_LLM_URL": "http://127.0.0.1:8000/v1",
    "GLM_KEY": "k-glm",
    "DSK_KEY": "k-dsk",
    "QWEN_KEY": "k-qwen",
}


@pytest.fixture()
def data():
    with mock.patch.dict(os.environ, ENV, clear=True):
        yield load_config(CONFIG_PATH).data


def test_build_mock() -> None:
    assert isinstance(build_llm("generator", {}, mock=True), MockLLM)


def test_build_real_client(data) -> None:
    client = build_llm("generator", data)
    assert isinstance(client, OpenAICompatLLM)
    assert client.model == "glm-5"
    assert client.base_url == "https://glm.example.com/v4"
    assert client.api_key == "k-glm"
    assert client.timeout == 120


def test_build_local_without_key(data) -> None:
    client = build_llm("judge_qwen", data)
    assert isinstance(client, OpenAICompatLLM)
    assert client.api_key == "k-dsk"


def test_unknown_role(data) -> None:
    with pytest.raises(ConfigError):
        build_llm("nope", data)


def test_missing_env_raises() -> None:
    with mock.patch.dict(os.environ, {}, clear=True):
        cfg = load_config(CONFIG_PATH)
    with pytest.raises(ConfigError):
        build_llm("generator", cfg.data)


def test_unsupported_style(data) -> None:
    data["providers"]["glm"]["api_style"] = "anthropic"
    with pytest.raises(ConfigError, match="api_style"):
        build_llm("generator", data)


def test_custom_headers_and_timeout() -> None:
    data = {
        "providers": {
            "x": {
                "base_url": "http://x/v1",
                "api_key_env": "X_KEY",
                "timeout": 30,
                "headers": {"X-Org": "acme"},
            }
        },
        "roles": {"generator": {"provider": "x", "model": "m"}},
    }
    with mock.patch.dict(os.environ, {"X_KEY": "kx"}, clear=True):
        client = build_llm("generator", data)
    assert client.timeout == 30
    assert client.headers == {"X-Org": "acme"}


def test_describe_roles_all_ok(data) -> None:
    rows = describe_roles(data)
    assert len(rows) == 5
    assert all(row["status"] == "ok" for row in rows)
    assert all(row["api_key"] == "已配置" for row in rows)


def test_describe_roles_reports_errors() -> None:
    with mock.patch.dict(os.environ, {}, clear=True):
        cfg = load_config(CONFIG_PATH)
    rows = describe_roles(cfg.data)
    assert all(row["status"] == "error" for row in rows)
    assert all("未解析" in row["error"] for row in rows)
