"""配置层测试：YAML 解析、${ENV} 展开、供应商/角色解析、静态校验。"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

import pytest

from prompt5.config import (
    ConfigError,
    get_path,
    load_config,
    parse_yaml_text,
    resolve_provider,
    resolve_role,
    validate_config,
)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.example.yaml"

ENV_FULL = {
    "GLM_URL": "http://glm.local/v1",
    "DSK_URL": "http://dsk.local/v1",
    "QWEN_URL": "http://qwen.local/v1",
    "LOCAL_LLM_URL": "http://127.0.0.1:8000/v1",
    "GLM_KEY": "key-glm",
    "DSK_KEY": "key-dsk",
    "QWEN_KEY": "key-qwen",
}


@pytest.fixture()
def loaded():
    with mock.patch.dict(os.environ, ENV_FULL, clear=True):
        yield load_config(CONFIG_PATH)


class TestExampleConfig:
    def test_roles_reference_providers(self, loaded) -> None:
        assert get_path(loaded.data, "roles.generator.provider") == "glm"
        assert get_path(loaded.data, "roles.generator.model") == "glm-5"
        assert get_path(loaded.data, "roles.judge_dsk.provider") == "qwen"
        assert get_path(loaded.data, "roles.judge_dsk.model") == "qwen-max"

    def test_providers_fields(self, loaded) -> None:
        assert get_path(loaded.data, "providers.deepseek.api_key_env") == "DSK_KEY"
        assert get_path(loaded.data, "providers.local.api_key_required") is False
        assert get_path(loaded.data, "providers.glm.timeout") == 120

    def test_targets_and_labels(self, loaded) -> None:
        assert get_path(loaded.data, "targets.glm5.tier") == "T2"
        assert get_path(loaded.data, "targets.qwen_oss.provider") == "local"
        assert get_path(loaded.data, "targets.qwen_oss.label") == "compatible"

    def test_budgets_types(self, loaded) -> None:
        assert get_path(loaded.data, "budgets.per_task_tokens") == 250000
        assert get_path(loaded.data, "budgets.queue_sla_p95") == "600s"

    def test_connector_list_of_maps(self, loaded) -> None:
        connectors = loaded.data["connectors"]
        assert len(connectors) == 1
        conn = connectors[0]
        assert conn["id"] == "host-agent-alpha"
        assert conn["scopes"] == ["discovery.v1", "generate.v1", "render.v1", "score.v1"]
        assert conn["callbacks"]["retry"]["max_attempts"] == 5

    def test_env_expansion(self, loaded) -> None:
        assert get_path(loaded.data, "providers.glm.base_url") == "http://glm.local/v1"
        assert get_path(loaded.data, "providers.qwen.base_url") == "http://qwen.local/v1"
        assert loaded.missing_env == []

    def test_missing_env_collected(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = load_config(CONFIG_PATH)
        for name in ("GLM_URL", "DSK_URL", "QWEN_URL", "LOCAL_LLM_URL"):
            assert name in cfg.missing_env
        assert get_path(cfg.data, "providers.glm.base_url") == "${GLM_URL}"


class TestResolveProvider:
    def test_ok(self, loaded) -> None:
        provider = resolve_provider(loaded.data, "glm")
        assert provider.base_url == "http://glm.local/v1"
        assert provider.api_key == "key-glm"
        assert provider.timeout == 120
        assert provider.api_style == "openai"

    def test_local_without_key(self, loaded) -> None:
        provider = resolve_provider(loaded.data, "local")
        assert provider.api_key == ""

    def test_unknown_provider(self, loaded) -> None:
        with pytest.raises(ConfigError, match="unknown provider"):
            resolve_provider(loaded.data, "nope")

    def test_unresolved_url(self, loaded) -> None:
        data = {"providers": {"x": {"base_url": "${MISSING_URL}", "api_key_env": "K"}}}
        with pytest.raises(ConfigError, match="未解析"):
            resolve_provider(data, "x")

    def test_missing_key(self) -> None:
        data = {"providers": {"x": {"base_url": "http://x/v1", "api_key_env": "NO_SUCH_KEY"}}}
        with mock.patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigError, match="缺少 API 密钥"):
                resolve_provider(data, "x")

    def test_inline_key_fallback(self) -> None:
        data = {"providers": {"x": {"base_url": "http://x/v1", "api_key": "plain-key"}}}
        assert resolve_provider(data, "x").api_key == "plain-key"


class TestResolveRole:
    def test_via_provider(self, loaded) -> None:
        binding = resolve_role(loaded.data, "generator")
        assert binding.provider.name == "glm"
        assert binding.model == "glm-5"
        assert binding.provider.api_key == "key-glm"

    def test_legacy_inline_role(self) -> None:
        data = {
            "roles": {
                "generator": {
                    "model": "legacy-model",
                    "base_url": "http://legacy.local/v1",
                    "api_key_env": "LEGACY_KEY",
                }
            }
        }
        with mock.patch.dict(os.environ, {"LEGACY_KEY": "k"}, clear=True):
            binding = resolve_role(data, "generator")
        assert binding.provider.base_url == "http://legacy.local/v1"
        assert binding.provider.name == "inline:generator"

    def test_unknown_role(self, loaded) -> None:
        with pytest.raises(ConfigError, match="unknown role"):
            resolve_role(loaded.data, "nope")

    def test_missing_model(self) -> None:
        data = {"roles": {"generator": {"provider": "glm"}}}
        with pytest.raises(ConfigError, match="model"):
            resolve_role(data, "generator")


class TestValidateConfig:
    def test_clean_when_env_present(self, loaded) -> None:
        issues = validate_config(loaded.data)
        assert [issue for issue in issues if issue.level == "error"] == []

    def test_missing_env_reported(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = load_config(CONFIG_PATH)
        codes = {issue.code for issue in validate_config(cfg.data)}
        assert "CFG_PROVIDER_URL_UNRESOLVED" in codes
        assert "CFG_PROVIDER_KEY_UNSET" in codes

    def test_local_no_key_not_an_error(self, loaded) -> None:
        issues = validate_config(loaded.data)
        assert not any(issue.code == "CFG_PROVIDER_KEY_UNSET" and "local" in issue.field for issue in issues)

    def test_unknown_provider_in_role(self, loaded) -> None:
        loaded.data["roles"]["generator"] = {"provider": "missing", "model": "glm-5"}
        codes = {issue.code for issue in validate_config(loaded.data)}
        assert "CFG_ROLE_UNKNOWN_PROVIDER" in codes

    def test_inline_key_warns(self, loaded) -> None:
        loaded.data["providers"]["glm"]["api_key"] = "sk-plain"
        issues = validate_config(loaded.data)
        assert any(issue.code == "CFG_PROVIDER_KEY_INLINE" and issue.level == "warn" for issue in issues)

    def test_bad_label_warns(self, loaded) -> None:
        loaded.data["targets"]["glm5"]["label"] = "best"
        issues = validate_config(loaded.data)
        assert any(issue.code == "CFG_TARGET_LABEL" and issue.level == "warn" for issue in issues)

    def test_bad_budget_type(self, loaded) -> None:
        loaded.data["budgets"]["per_task_tokens"] = "250k"
        issues = validate_config(loaded.data)
        assert any(issue.code == "CFG_BUDGET_TYPE" and issue.level == "error" for issue in issues)

    def test_unsupported_api_style(self, loaded) -> None:
        loaded.data["providers"]["glm"]["api_style"] = "anthropic"
        issues = validate_config(loaded.data)
        assert any(issue.code == "CFG_PROVIDER_STYLE" for issue in issues)


class ParserStrictnessTest(unittest.TestCase):
    def test_flow_structures(self) -> None:
        data = parse_yaml_text('a: {b: [1, 2], c: "x"}\nd: 3\n')
        assert data == {"a": {"b": [1, 2], "c": "x"}, "d": 3}

    def test_comments_ignored(self) -> None:
        assert parse_yaml_text("# head\na: 1  # trailing\n") == {"a": 1}

    def test_tab_indent_rejected(self) -> None:
        with pytest.raises(ConfigError):
            parse_yaml_text("a:\n\tb: 1\n")

    def test_top_level_list_rejected(self) -> None:
        with pytest.raises(ConfigError):
            parse_yaml_text("- a\n- b\n")

    def test_missing_file(self) -> None:
        with pytest.raises(ConfigError):
            load_config(CONFIG_PATH.with_name("no-such-file.yaml"))
