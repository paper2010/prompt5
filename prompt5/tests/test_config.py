"""配置层测试：YAML 解析、${ENV} 展开、供应商/角色/裁判池/目标解析、静态校验。"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

import pytest

from prompt5.config import (
    ConfigError,
    get_path,
    judge_pool,
    load_config,
    parse_yaml_text,
    primary_target,
    resolve_judge,
    resolve_provider,
    resolve_role,
    resolve_target,
    validate_config,
)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.example.yaml"

ENV_FULL = {
    "DSK_URL": "http://dsk.local/v1",
    "ZHIPU_URL": "http://zhipu.local/v4",
    "MIMO_URL": "http://mimo.local/v1",
    "KIMI_URL": "http://kimi.local/v1",
    "MINIMAX_URL": "http://minimax.local/v1",
    "LOCAL_LLM_URL": "http://127.0.0.1:8000/v1",
    "DSK_KEY": "key-dsk",
    "ZHIPU_KEY": "key-zhipu",
    "MIMO_KEY": "key-mimo",
    "KIMI_KEY": "key-kimi",
    "MINIMAX_KEY": "key-minimax",
}


@pytest.fixture()
def loaded():
    with mock.patch.dict(os.environ, ENV_FULL, clear=True):
        yield load_config(CONFIG_PATH)


class TestExampleConfig:
    def test_roles_reference_providers(self, loaded) -> None:
        assert get_path(loaded.data, "roles.generator.provider") == "deepseek"
        assert get_path(loaded.data, "roles.generator.model") == "deepseek-chat"
        judges = judge_pool(loaded.data)
        assert len(judges) == 4
        assert judges[0]["provider"] == "zhipu"

    def test_providers_fields(self, loaded) -> None:
        assert get_path(loaded.data, "providers.zhipu.api_key_env") == "ZHIPU_KEY"
        assert get_path(loaded.data, "providers.local.api_key_required") is False
        assert get_path(loaded.data, "providers.deepseek.timeout") == 120

    def test_targets_and_primary(self, loaded) -> None:
        assert get_path(loaded.data, "targets.deepseek.primary") is True
        assert get_path(loaded.data, "targets.qwen_oss.provider") == "local"
        assert primary_target(loaded.data) == "deepseek"

    def test_budgets_types(self, loaded) -> None:
        assert get_path(loaded.data, "budgets.per_task_tokens") == 250000
        assert get_path(loaded.data, "budgets.queue_sla_p95") == "600s"

    def test_connector_list_of_maps(self, loaded) -> None:
        connectors = loaded.data["connectors"]
        assert len(connectors) == 1
        assert connectors[0]["id"] == "host-agent-alpha"
        assert "generate.v1" in connectors[0]["scopes"]
        assert connectors[0]["callbacks"]["retry"]["max_attempts"] == 5

    def test_env_expansion(self, loaded) -> None:
        assert get_path(loaded.data, "providers.deepseek.base_url") == "http://dsk.local/v1"
        assert get_path(loaded.data, "providers.minimax.base_url") == "http://minimax.local/v1"
        assert loaded.missing_env == []

    def test_missing_env_collected(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = load_config(CONFIG_PATH)
        for name in ("DSK_URL", "ZHIPU_URL", "MIMO_URL", "KIMI_URL", "MINIMAX_URL", "LOCAL_LLM_URL"):
            assert name in cfg.missing_env
        assert get_path(cfg.data, "providers.deepseek.base_url") == "${DSK_URL}"


class TestResolveProvider:
    def test_ok(self, loaded) -> None:
        provider = resolve_provider(loaded.data, "deepseek")
        assert provider.base_url == "http://dsk.local/v1"
        assert provider.api_key == "key-dsk"
        assert provider.timeout == 120

    def test_local_without_key(self, loaded) -> None:
        assert resolve_provider(loaded.data, "local").api_key == ""

    def test_unknown_provider(self, loaded) -> None:
        with pytest.raises(ConfigError, match="unknown provider"):
            resolve_provider(loaded.data, "nope")

    def test_unresolved_url(self) -> None:
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
        assert binding.provider.name == "deepseek"
        assert binding.model == "deepseek-chat"

    def test_unknown_role(self, loaded) -> None:
        with pytest.raises(ConfigError, match="unknown role"):
            resolve_role(loaded.data, "nope")

    def test_missing_model(self) -> None:
        data = {"roles": {"generator": {"provider": "deepseek"}}}
        with pytest.raises(ConfigError, match="model"):
            resolve_role(data, "generator")


class TestResolveJudge:
    def test_picks_non_conflicting_family(self, loaded) -> None:
        # 被测 deepseek、生成器 deepseek → 裁判不能是 deepseek；池首项 zhipu 命中
        binding = resolve_judge(loaded.data, "deepseek")
        assert binding.family == "zhipu"
        assert binding.model

    def test_skips_target_family(self, loaded) -> None:
        # 被测 zhipu → 跳过 zhipu，取 kimi
        assert resolve_judge(loaded.data, "zhipu").family == "kimi"

    def test_skips_generator_family(self, loaded) -> None:
        assert resolve_judge(loaded.data, "kimi").family == "zhipu"

    def test_no_candidate_raises(self) -> None:
        data = {
            "providers": {"deepseek": {"base_url": "http://d/v1", "api_key_env": "K"}},
            "roles": {
                "generator": {"provider": "deepseek", "model": "m"},
                "judges": [{"provider": "deepseek", "model": "m2"}],
            },
        }
        with mock.patch.dict(os.environ, {"K": "x"}, clear=True):
            with pytest.raises(ConfigError, match="无可用裁判"):
                resolve_judge(data, "deepseek")


class TestResolveTarget:
    def test_ok(self, loaded) -> None:
        provider, model, raw = resolve_target(loaded.data, "kimi")
        assert provider.name == "kimi"
        assert model == "kimi-k2"
        assert raw["label"] == "compatible"

    def test_unknown(self, loaded) -> None:
        with pytest.raises(ConfigError, match="unknown target"):
            resolve_target(loaded.data, "nope")

    def test_no_provider(self, loaded) -> None:
        loaded.data["targets"]["broken"] = {"model": "m"}
        with pytest.raises(ConfigError, match="provider"):
            resolve_target(loaded.data, "broken")


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
        loaded.data["roles"]["generator"] = {"provider": "missing", "model": "m"}
        codes = {issue.code for issue in validate_config(loaded.data)}
        assert "CFG_ROLE_UNKNOWN_PROVIDER" in codes

    def test_judges_missing(self, loaded) -> None:
        loaded.data["roles"].pop("judges")
        codes = {issue.code for issue in validate_config(loaded.data)}
        assert "CFG_NO_JUDGES" in codes

    def test_judge_unknown_provider(self, loaded) -> None:
        loaded.data["roles"]["judges"] = [{"provider": "ghost", "model": "m"}]
        codes = {issue.code for issue in validate_config(loaded.data)}
        assert "CFG_JUDGE_UNKNOWN_PROVIDER" in codes

    def test_judge_pool_thin_warns(self, loaded) -> None:
        loaded.data["roles"]["judges"] = [{"provider": "zhipu", "model": "m"}]
        issues = validate_config(loaded.data)
        assert any(issue.code == "CFG_JUDGE_POOL_THIN" and issue.level == "warn" for issue in issues)

    def test_multi_primary(self, loaded) -> None:
        loaded.data["targets"]["kimi"]["primary"] = True
        codes = {issue.code for issue in validate_config(loaded.data)}
        assert "CFG_MULTI_PRIMARY" in codes

    def test_inline_key_warns(self, loaded) -> None:
        loaded.data["providers"]["deepseek"]["api_key"] = "sk-plain"
        issues = validate_config(loaded.data)
        assert any(issue.code == "CFG_PROVIDER_KEY_INLINE" and issue.level == "warn" for issue in issues)

    def test_bad_label_warns(self, loaded) -> None:
        loaded.data["targets"]["deepseek"]["label"] = "best"
        issues = validate_config(loaded.data)
        assert any(issue.code == "CFG_TARGET_LABEL" and issue.level == "warn" for issue in issues)

    def test_bad_budget_type(self, loaded) -> None:
        loaded.data["budgets"]["per_task_tokens"] = "250k"
        issues = validate_config(loaded.data)
        assert any(issue.code == "CFG_BUDGET_TYPE" and issue.level == "error" for issue in issues)

    def test_unsupported_api_style(self, loaded) -> None:
        loaded.data["providers"]["deepseek"]["api_style"] = "anthropic"
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
