"""配置加载：YAML（优先 PyYAML）→ dict，含 ${ENV} 展开与缺失环境变量登记。

当前环境无 PyYAML（见 NOTES.md #1），内置最小 YAML 子集解析器，仅支持本项目
config 结构：缩进映射、行内 flow map/list、引号/数字/布尔/null 标量、注释。
子集外语法一律抛 ConfigError（保守失败，绝不猜测）。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["ConfigError", "LoadedConfig", "load_config", "get_path"]

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(ValueError):
    """配置语法不受支持或结构非法。"""


@dataclass
class LoadedConfig:
    data: dict
    missing_env: list[str] = field(default_factory=list)
    source: str = ""

    def __getitem__(self, key: str) -> Any:
        return self.data[key]


def get_path(data: dict, dotted: str, default: Any = None) -> Any:
    """点路径取值：get_path(cfg, "roles.generator.model")。"""
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


# ---------------------------------------------------------------- env expansion
def _expand_env(node: Any, missing: list[str]) -> Any:
    if isinstance(node, str):
        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            if name in os.environ:
                return os.environ[name]
            if name not in missing:
                missing.append(name)
            return match.group(0)

        return _ENV_RE.sub(repl, node)
    if isinstance(node, list):
        return [_expand_env(item, missing) for item in node]
    if isinstance(node, dict):
        return {key: _expand_env(value, missing) for key, value in node.items()}
    return node


# ---------------------------------------------------------------- fallback yaml
def _strip_comment(line: str) -> str:
    in_single = in_double = False
    for idx, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if idx == 0 or line[idx - 1] in " \t":
                return line[:idx]
    return line


def _unquote(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] == '"':
        body = text[1:-1]
        return body.replace('\\"', '"').replace("\\\\", "\\")
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1].replace("''", "'")
    return text


def _parse_scalar(text: str) -> Any:
    text = text.strip()
    if text == "" or text in ("~", "null", "Null", "NULL"):
        return None
    if text in ("true", "True", "TRUE"):
        return True
    if text in ("false", "False", "FALSE"):
        return False
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return _unquote(text)
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+([eE][-+]?\d+)?", text):
        return float(text)
    return text


class _FlowParser:
    """行内 flow 值：{k: v, ...} / [a, b] / 标量。"""

    def __init__(self, text: str):
        self.text = text
        self.pos = 0

    def parse(self) -> Any:
        value = self._value()
        self._skip_ws()
        if self.pos != len(self.text):
            raise ConfigError(f"trailing characters in flow value: {self.text!r}")
        return value

    def _skip_ws(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] in " \t":
            self.pos += 1

    def _peek(self) -> str:
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def _value(self) -> Any:
        self._skip_ws()
        ch = self._peek()
        if ch == "{":
            return self._mapping()
        if ch == "[":
            return self._sequence()
        return self._scalar()

    def _mapping(self) -> dict:
        self.pos += 1  # {
        result: dict = {}
        self._skip_ws()
        if self._peek() == "}":
            self.pos += 1
            return result
        while True:
            key = self._key()
            self._skip_ws()
            if self._peek() != ":":
                raise ConfigError(f"expected ':' in flow map near {self.text[self.pos:]!r}")
            self.pos += 1
            result[key] = self._value()
            self._skip_ws()
            ch = self._peek()
            if ch == ",":
                self.pos += 1
                continue
            if ch == "}":
                self.pos += 1
                return result
            raise ConfigError(f"expected ',' or '}}' in flow map near {self.text[self.pos:]!r}")

    def _sequence(self) -> list:
        self.pos += 1  # [
        result: list = []
        self._skip_ws()
        if self._peek() == "]":
            self.pos += 1
            return result
        while True:
            result.append(self._value())
            self._skip_ws()
            ch = self._peek()
            if ch == ",":
                self.pos += 1
                continue
            if ch == "]":
                self.pos += 1
                return result
            raise ConfigError(f"expected ',' or ']' in flow list near {self.text[self.pos:]!r}")

    def _key(self) -> str:
        self._skip_ws()
        if self._peek() in "\"'":
            return self._quoted()
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] not in ":,}":
            self.pos += 1
        key = self.text[start:self.pos].strip()
        if not key:
            raise ConfigError("empty key in flow map")
        return key

    def _quoted(self) -> str:
        quote = self.text[self.pos]
        start = self.pos
        self.pos += 1
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch == "\\" and quote == '"':
                self.pos += 2
                continue
            if ch == quote:
                self.pos += 1
                return _unquote(self.text[start:self.pos])
            self.pos += 1
        raise ConfigError("unterminated quoted string")

    def _scalar(self) -> Any:
        if self._peek() in "\"'":
            return self._quoted()
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] not in ",}]":
            self.pos += 1
        return _parse_scalar(self.text[start:self.pos])


def _parse_flow(text: str) -> Any:
    text = text.strip()
    if text[:1] in "{[":
        return _FlowParser(text).parse()
    return _parse_scalar(text)


def _parse_block(lines: list[tuple[int, str, int]], start: int, indent: int) -> tuple[Any, int]:
    """递归下降：解析 indent 层级的映射或列表，返回 (value, next_line_index)。"""
    idx = start
    if idx < len(lines) and lines[idx][1].startswith("- "):
        result_list: list = []
        while idx < len(lines):
            cur_indent, text, lineno = lines[idx]
            if cur_indent != indent or not text.startswith("- "):
                break
            item_text = text[2:].strip()
            item_indent = indent + 2
            if item_text == "":
                if idx + 1 >= len(lines):
                    raise ConfigError(f"empty list item at line {lineno}")
                value, idx = _parse_block(lines, idx + 1, lines[idx + 1][0])
                result_list.append(value)
                continue
            if ":" in item_text and not item_text.startswith(("{", "[")):
                # 列表项是映射（行内首键 + 后续同缩进键）
                sub: list[tuple[int, str, int]] = [(item_indent, item_text, lineno)]
                idx += 1
                while idx < len(lines) and lines[idx][0] >= item_indent:
                    sub.append(lines[idx])
                    idx += 1
                value, consumed = _parse_block(sub, 0, item_indent)
                if consumed != len(sub):
                    raise ConfigError(f"unparsed list item content at line {lineno}")
                result_list.append(value)
                continue
            result_list.append(_parse_flow(item_text))
            idx += 1
        return result_list, idx

    result_map: dict = {}
    while idx < len(lines):
        cur_indent, text, lineno = lines[idx]
        if cur_indent < indent:
            break
        if cur_indent > indent:
            raise ConfigError(f"unexpected indentation at line {lineno}: {text!r}")
        if text.startswith("- "):
            break
        if ":" not in text:
            raise ConfigError(f"expected 'key: value' at line {lineno}: {text!r}")
        key, _, rest = text.partition(":")
        key = key.strip()
        if not key:
            raise ConfigError(f"empty key at line {lineno}")
        rest = rest.strip()
        if rest == "":
            if idx + 1 < len(lines) and lines[idx + 1][0] > indent:
                value, idx = _parse_block(lines, idx + 1, lines[idx + 1][0])
                result_map[key] = value
                continue
            result_map[key] = None
            idx += 1
            continue
        result_map[key] = _parse_flow(rest)
        idx += 1
    return result_map, idx


def parse_yaml_text(text: str) -> dict:
    """最小 YAML 子集解析（顶层必须是映射）。"""
    lines: list[tuple[int, str, int]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw.split("#", 1)[0]:
            raise ConfigError(f"tabs are not allowed (line {lineno})")
        stripped = _strip_comment(raw).rstrip()
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append((indent, stripped.lstrip(" "), lineno))
    if not lines:
        return {}
    value, next_idx = _parse_block(lines, 0, lines[0][0])
    if next_idx != len(lines):
        raise ConfigError(f"unparsed content starting at line {lines[next_idx][2]}")
    if not isinstance(value, dict):
        raise ConfigError("top-level YAML must be a mapping")
    return value


# ---------------------------------------------------------------- public loader
def load_config(path: str | Path) -> LoadedConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]

        data = yaml.safe_load(text) or {}
    except ImportError:
        data = parse_yaml_text(text)
    if not isinstance(data, dict):
        raise ConfigError("config root must be a mapping")
    missing: list[str] = []
    expanded = _expand_env(data, missing)
    return LoadedConfig(data=expanded, missing_env=missing, source=str(path))


# ---------------------------------------------------------------- providers
@dataclass
class ProviderConfig:
    """解析后的供应商连接信息（端点 + 密钥 + 超时 + 额外头）。"""

    name: str
    base_url: str
    api_key: str
    timeout: float = 120.0
    headers: dict[str, str] = field(default_factory=dict)
    api_style: str = "openai"
    display: str = ""


@dataclass
class RoleBinding:
    role: str
    provider: ProviderConfig
    model: str


@dataclass
class Issue:
    level: str  # error | warn
    code: str
    field: str
    message: str


def resolve_provider(data: dict, name: str) -> ProviderConfig:
    """解析单个供应商；缺环境变量、端点非法、密钥缺失都在此明确报错。"""
    providers = data.get("providers") or {}
    if name not in providers:
        raise ConfigError(f"unknown provider {name!r}（providers 中未定义）")
    raw = providers[name] or {}

    base_url = str(raw.get("base_url", "")).strip()
    if not base_url:
        raise ConfigError(f"provider {name!r} 缺少 base_url")
    if "${" in base_url:
        raise ConfigError(
            f"provider {name!r} 的 base_url 未解析（环境变量缺失）：{base_url!r}"
        )

    api_key = ""
    env_name = str(raw.get("api_key_env", "")).strip()
    if env_name:
        api_key = os.environ.get(env_name, "")
    if not api_key:
        inline = str(raw.get("api_key", "")).strip()
        if inline and "${" not in inline:
            api_key = inline
    required = bool(raw.get("api_key_required", True))
    if required and not api_key:
        raise ConfigError(
            f"provider {name!r} 缺少 API 密钥：请设置环境变量 {env_name or '<api_key_env 未配置>'}，"
            f"或在配置中提供 api_key（不推荐提交到仓库）"
        )

    headers = {str(k): str(v) for k, v in (raw.get("headers") or {}).items()}
    return ProviderConfig(
        name=name,
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        timeout=float(raw.get("timeout", 120)),
        headers=headers,
        api_style=str(raw.get("api_style", "openai")),
        display=str(raw.get("display", name)),
    )


def resolve_role(data: dict, role: str) -> RoleBinding:
    """角色 → 供应商 + 模型。兼容旧写法（角色内直接写 base_url/api_key_env）。"""
    roles = data.get("roles") or {}
    if role not in roles:
        raise ConfigError(f"unknown role {role!r}（roles 中未定义）")
    raw = roles[role] or {}
    model = str(raw.get("model", "")).strip()
    if not model or "${" in model:
        raise ConfigError(f"role {role!r} 缺少可用 model")

    if raw.get("provider"):
        provider = resolve_provider(data, str(raw["provider"]))
        return RoleBinding(role=role, provider=provider, model=model)

    # 旧写法：角色内联端点
    base_url = str(raw.get("base_url", "")).strip()
    if not base_url or "${" in base_url:
        raise ConfigError(f"role {role!r} 既无 provider，也无可用 base_url")
    env_name = str(raw.get("api_key_env", "")).strip()
    api_key = os.environ.get(env_name, "") if env_name else ""
    if not api_key:
        raise ConfigError(f"role {role!r} 缺少 API 密钥环境变量（{env_name or '未配置'}）")
    provider = ProviderConfig(
        name=f"inline:{role}",
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        timeout=float(raw.get("timeout", 120)),
    )
    return RoleBinding(role=role, provider=provider, model=model)


def validate_config(data: dict) -> list[Issue]:
    """静态校验：不抛异常，返回问题列表（error 阻断、warn 提示）。"""
    issues: list[Issue] = []
    providers = data.get("providers") or {}
    roles = data.get("roles") or {}
    targets = data.get("targets") or {}

    if not providers:
        issues.append(Issue("error", "CFG_NO_PROVIDERS", "providers", "未定义任何供应商"))

    for name, raw in providers.items():
        raw = raw or {}
        base_url = str(raw.get("base_url", "")).strip()
        if not base_url:
            issues.append(Issue("error", "CFG_PROVIDER_NO_URL", f"providers.{name}.base_url", "缺少端点地址"))
        elif "${" in base_url:
            issues.append(
                Issue("error", "CFG_PROVIDER_URL_UNRESOLVED", f"providers.{name}.base_url",
                      f"环境变量未设置，占位符未解析：{base_url}")
            )
        env_name = str(raw.get("api_key_env", "")).strip()
        inline = str(raw.get("api_key", "")).strip()
        required = bool(raw.get("api_key_required", True))
        if required and not env_name and not inline:
            issues.append(
                Issue("error", "CFG_PROVIDER_NO_KEY", f"providers.{name}",
                      "缺少 api_key_env 或 api_key")
            )
        if required and env_name and not os.environ.get(env_name) and not inline:
            issues.append(
                Issue("error", "CFG_PROVIDER_KEY_UNSET", f"providers.{name}.api_key_env",
                      f"环境变量 {env_name} 未设置")
            )
        if inline and "${" not in inline:
            issues.append(
                Issue("warn", "CFG_PROVIDER_KEY_INLINE", f"providers.{name}.api_key",
                      "检测到明文密钥，建议改用 api_key_env 并从环境变量读取")
            )
        if raw.get("api_style", "openai") != "openai":
            issues.append(
                Issue("error", "CFG_PROVIDER_STYLE", f"providers.{name}.api_style",
                      "当前仅支持 openai 兼容协议")
            )

    if not roles:
        issues.append(Issue("error", "CFG_NO_ROLES", "roles", "未定义任何角色"))

    for role, raw in roles.items():
        raw = raw or {}
        if not str(raw.get("model", "")).strip():
            issues.append(Issue("error", "CFG_ROLE_NO_MODEL", f"roles.{role}.model", "缺少模型名"))
        if raw.get("provider"):
            if raw["provider"] not in providers:
                issues.append(
                    Issue("error", "CFG_ROLE_UNKNOWN_PROVIDER", f"roles.{role}.provider",
                          f"未定义的供应商 {raw['provider']!r}")
                )
        elif not raw.get("base_url"):
            issues.append(
                Issue("error", "CFG_ROLE_NO_TARGET", f"roles.{role}",
                      "需提供 provider，或旧写法的 base_url + api_key_env")
            )

    for name, raw in targets.items():
        raw = raw or {}
        if not str(raw.get("model", "")).strip():
            issues.append(Issue("error", "CFG_TARGET_NO_MODEL", f"targets.{name}.model", "缺少模型名"))
        if raw.get("provider") and raw["provider"] not in providers:
            issues.append(
                Issue("error", "CFG_TARGET_UNKNOWN_PROVIDER", f"targets.{name}.provider",
                      f"未定义的供应商 {raw['provider']!r}")
            )
        if str(raw.get("label", "")) not in {"", "optimizing", "compatible", "rejected"}:
            issues.append(
                Issue("warn", "CFG_TARGET_LABEL", f"targets.{name}.label",
                      f"未知标签 {raw.get('label')!r}，仅允许 optimizing/compatible/rejected")
            )

    budgets = data.get("budgets") or {}
    for key in ("per_task_tokens", "tenant_daily_tokens", "global_concurrent_tasks"):
        if key in budgets and not isinstance(budgets[key], int):
            issues.append(Issue("error", "CFG_BUDGET_TYPE", f"budgets.{key}", "必须为整数"))
    return issues
