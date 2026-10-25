"""配置生效链路：角色/裁判池/被测目标 → 客户端与执行器（不发起网络请求）。"""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from prompt5.config import ConfigError, load_config
from prompt5.llm.client import MockLLM, OpenAICompatLLM
from prompt5.llm.roles import (
    build_executor,
    build_generator,
    build_judge,
    build_llm,
    build_target_client,
    describe_roles,
    describe_targets,
)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.example.yaml"
ENV = {
    "DSK_URL": "https://dsk.example.com/v1",
    "ZHIPU_URL": "https://zhipu.example.com/v4",
    "MIMO_URL": "https://mimo.example.com/v1",
    "KIMI_URL": "https://kimi.example.com/v1",
    "MINIMAX_URL": "https://minimax.example.com/v1",
    "LOCAL_LLM_URL": "http://127.0.0.1:8000/v1",
    "DSK_KEY": "k-dsk",
    "ZHIPU_KEY": "k-zhipu",
    "MIMO_KEY": "k-mimo",
    "KIMI_KEY": "k-kimi",
    "MINIMAX_KEY": "k-minimax",
}


@pytest.fixture()
def data():
    with mock.patch.dict(os.environ, ENV, clear=True):
        yield load_config(CONFIG_PATH).data


def test_build_mock() -> None:
    assert isinstance(build_llm("generator", {}, mock=True), MockLLM)


def test_build_generator(data) -> None:
    client = build_generator(data)
    assert isinstance(client, OpenAICompatLLM)
    assert client.model == "deepseek-chat"
    assert client.base_url == "https://dsk.example.com/v1"
    assert client.api_key == "k-dsk"
    assert client.timeout == 120


def test_build_judge_avoids_target_and_generator(data) -> None:
    judge, meta = build_judge(data, "deepseek")
    assert meta["family"] == "zhipu"
    assert meta["model"]
    assert judge.model_snapshot.startswith("zhipu/")


def test_build_judge_switch_by_target(data) -> None:
    _, meta_zhipu = build_judge(data, "zhipu")
    assert meta_zhipu["family"] == "kimi"
    _, meta_kimi = build_judge(data, "kimi")
    assert meta_kimi["family"] == "zhipu"


def test_build_judge_no_candidate() -> None:
    data = {
        "providers": {"deepseek": {"base_url": "http://d/v1", "api_key_env": "K"}},
        "roles": {
            "generator": {"provider": "deepseek", "model": "m"},
            "judges": [{"provider": "deepseek", "model": "m2"}],
        },
    }
    with mock.patch.dict(os.environ, {"K": "x"}, clear=True):
        with pytest.raises(ConfigError):
            build_judge(data, "deepseek")


def test_build_target_client_local_without_key(data) -> None:
    client, meta = build_target_client(data, "qwen_oss")
    assert client.api_key == ""
    assert meta["provider"] == "local"
    assert meta["tier"] == "T1"


def test_build_target_client_defaults_to_primary(data) -> None:
    _, meta = build_target_client(data)
    assert meta["target"] == "deepseek"
    assert meta["primary"] is True


def test_build_executor(data) -> None:
    executor, meta = build_executor(data, "kimi")
    assert executor.name == "live:kimi-k2"
    assert meta["target"] == "kimi"


def test_executor_calls_client(data, monkeypatch) -> None:
    executor, _ = build_executor(data, "deepseek")
    captured = {}

    def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return "pong"

    monkeypatch.setattr(executor.client, "chat", fake_chat)
    output = executor.execute("提示词全文", {"model_budget": {"max_tokens": 64}})
    assert output == "pong"
    assert captured["messages"][0]["content"] == "提示词全文"
    assert captured["kwargs"]["max_tokens"] == 64
    assert captured["kwargs"]["temperature"] == 0.0


def test_missing_env_raises() -> None:
    with mock.patch.dict(os.environ, {}, clear=True):
        cfg = load_config(CONFIG_PATH)
    with pytest.raises(ConfigError):
        build_generator(cfg.data)


def test_unsupported_style(data) -> None:
    data["providers"]["deepseek"]["api_style"] = "anthropic"
    with pytest.raises(ConfigError, match="api_style"):
        build_generator(data)


def test_describe_roles_includes_judges(data) -> None:
    rows = describe_roles(data)
    labels = [row["role"] for row in rows]
    assert labels == ["generator", "reflector", "judge:zhipu", "judge:kimi", "judge:minimax", "judge:mimo"]
    assert all(row["status"] == "ok" for row in rows)


def test_describe_targets_marks_primary(data) -> None:
    rows = describe_targets(data)
    primary = [row for row in rows if row["primary"]]
    assert len(primary) == 1 and primary[0]["target"] == "deepseek"
    assert {row["target"] for row in rows} == {"deepseek", "zhipu", "kimi", "minimax", "mimo", "qwen_oss"}


def test_describe_roles_reports_errors() -> None:
    with mock.patch.dict(os.environ, {}, clear=True):
        cfg = load_config(CONFIG_PATH)
    rows = describe_roles(cfg.data)
    assert any(row["status"] == "error" for row in rows)
