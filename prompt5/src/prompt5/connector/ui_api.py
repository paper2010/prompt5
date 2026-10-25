"""Prompt5 本地单用户 UI 的薄 HTTP 适配层。

只编排既有 IR/Patch/Ledger、评测、配置和 Session 能力，不重写核心算法。
隐藏基准内容、真实密钥和连接器配置均不进入 UI 响应。
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from fastapi import FastAPI, Header
from pydantic import ValidationError

from ..applier import ApplyError
from ..config import ConfigError, validate_config
from ..ids import new_patch_id
from ..llm.client import LLMError
from ..llm.roles import build_executor, build_target_client
from ..modules.m3_cards import render
from ..modules.m5_eval.l3_exec import ScriptedExecutor
from ..modules.m5_eval.runner import compare, evaluate
from ..modules.m6_events import pull
from ..modules.m7_bench import (
    BASELINE_ID,
    build_candidates,
    gate_for_model,
    load_bench,
    load_prereg,
)
from ..patch import Patch
from .api import ConnectorService, Context, ServiceError
from .rubric import build_rubric_draft

__all__ = ["register_ui_routes"]

_DEFAULT_ROOT = Path(__file__).resolve().parents[3]
_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _require_dict(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ServiceError("E_SCHEMA_INVALID", 422, f"{field} must be an object")
    return value


def _public_config(data: dict[str, Any]) -> dict[str, Any]:
    providers: dict[str, Any] = {}
    for name, raw_value in (data.get("providers") or {}).items():
        raw = raw_value or {}
        env_name = str(raw.get("api_key_env", ""))
        inline = str(raw.get("api_key", ""))
        providers[name] = {
            "display": raw.get("display", name),
            "base_url": raw.get("base_url", ""),
            "api_key_env": env_name,
            "api_style": raw.get("api_style", "openai"),
            "timeout": raw.get("timeout", 120),
            "api_key_required": bool(raw.get("api_key_required", True)),
            "key_configured": bool((env_name and os.environ.get(env_name)) or (inline and "${" not in inline)),
        }
    roles = data.get("roles") or {}
    return {
        "providers": providers,
        "roles": {
            "generator": copy.deepcopy(roles.get("generator") or {}),
            "reflector": copy.deepcopy(roles.get("reflector") or {}),
            "judges": copy.deepcopy(roles.get("judges") or []),
        },
        "targets": copy.deepcopy(data.get("targets") or {}),
    }


def _merge_ui_config(payload: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """仅合并 UI 白名单字段；connectors、budgets、inline key、headers 不由浏览器修改。"""
    merged = copy.deepcopy(current)
    providers = _require_dict(payload.get("providers"), "providers")
    roles = _require_dict(payload.get("roles"), "roles")
    targets = _require_dict(payload.get("targets"), "targets")
    provider_fields = {"display", "base_url", "api_key_env", "api_style", "timeout", "api_key_required"}
    merged["providers"] = {}
    for name, raw_value in providers.items():
        raw = _require_dict(raw_value, f"providers.{name}")
        existing = (current.get("providers") or {}).get(name) or {}
        cleaned = {key: raw[key] for key in provider_fields if key in raw}
        merged["providers"][name] = {**copy.deepcopy(existing), **cleaned}

    merged_roles = copy.deepcopy(current.get("roles") or {})
    for role in ("generator", "reflector"):
        raw = _require_dict(roles.get(role), f"roles.{role}")
        merged_roles[role] = {"provider": str(raw.get("provider", "")), "model": str(raw.get("model", ""))}
    judges = roles.get("judges")
    if not isinstance(judges, list):
        raise ServiceError("E_SCHEMA_INVALID", 422, "roles.judges must be a list")
    merged_roles["judges"] = [
        {
            "provider": str(_require_dict(item, f"roles.judges[{index}]").get("provider", "")),
            "model": str(_require_dict(item, f"roles.judges[{index}]").get("model", "")),
        }
        for index, item in enumerate(judges)
    ]
    merged["roles"] = merged_roles

    merged["targets"] = {}
    for name, raw_value in targets.items():
        raw = _require_dict(raw_value, f"targets.{name}")
        merged["targets"][name] = {
            "provider": str(raw.get("provider", "")),
            "model": str(raw.get("model", "")),
            "tier": str(raw.get("tier", "T2")),
            "label": str(raw.get("label", "compatible")),
            "primary": bool(raw.get("primary", False)),
        }
    return merged


def _missing_env(data: dict[str, Any]) -> list[str]:
    missing: set[str] = set()

    def scan(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                scan(item)
        elif isinstance(value, list):
            for item in value:
                scan(item)
        elif isinstance(value, str):
            for match in _ENV_RE.finditer(value):
                if not os.environ.get(match.group(1)):
                    missing.add(match.group(1))

    scan({key: data.get(key) for key in ("providers", "roles", "targets")})
    for raw_value in (data.get("providers") or {}).values():
        raw = raw_value or {}
        env_name = str(raw.get("api_key_env", ""))
        if raw.get("api_key_required", True) and env_name and not os.environ.get(env_name):
            missing.add(env_name)
    return sorted(missing)


def _check_result(data: dict[str, Any]) -> dict[str, Any]:
    issues = [
        {"level": issue.level, "code": issue.code, "field": issue.field, "message": issue.message}
        for issue in validate_config(data)
    ]
    return {
        "ok": not any(issue["level"] == "error" for issue in issues),
        "issues": issues,
        "missing_env": _missing_env(data),
        "source": "backend",
    }


def _write_config(path: Path, data: dict[str, Any]) -> None:
    try:
        import yaml
    except ImportError as exc:
        raise ServiceError("E_CONFIG_WRITE_UNAVAILABLE", 500, "PyYAML is required to save config") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.ui-tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            yaml.safe_dump(data, stream, allow_unicode=True, sort_keys=False)
        if path.exists():
            shutil.copy2(path, path.with_name(f"{path.name}.bak"))
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ServiceError("E_CONFIG_WRITE_FAILED", 500, str(exc)[:200]) from exc


def _safe_detail(config: dict[str, Any], exc: Exception) -> str:
    detail = str(exc)[:300]
    for raw_value in (config.get("providers") or {}).values():
        raw = raw_value or {}
        env_name = str(raw.get("api_key_env", ""))
        secrets = [raw.get("api_key"), os.environ.get(env_name) if env_name else ""]
        for secret in secrets:
            if secret and isinstance(secret, str):
                detail = detail.replace(secret, "***")
    return detail


def _evaluation_report(config: dict[str, Any], root: Path, target: str, executor_kind: str) -> dict[str, Any]:
    prereg = load_prereg(root / "benchmarks" / "preregistration.json")
    tasks = [task for task in load_bench(root / "benchmarks" / "tasks_m7.jsonl") if task.get("split") == "confirmatory"]
    if executor_kind == "scripted":
        executor = ScriptedExecutor()
    elif executor_kind == "live":
        try:
            executor, _ = build_executor(config, target)
        except ConfigError as exc:
            raise ServiceError("E_CONFIG_UNAVAILABLE", 422, _safe_detail(config, exc)) from exc
    else:
        raise ServiceError("E_SCHEMA_INVALID", 422, "executor must be scripted or live")

    report = evaluate(
        build_candidates(target),
        tasks,
        executor,
        model_snapshot=f"{target}@{executor.name}",
        repeats=3,
        bench_version=str(prereg["bench_version"]),
    )
    comparison = compare(report, "champion", BASELINE_ID, margin=float(prereg["thresholds"]["eps_ni"]))
    critical_failures = sum(
        1
        for task in tasks
        if task.get("critical") and report.summary.get(task["task_id"], {}).get("champion", {}).get("pass_rate", 0.0) < 1.0
    )
    gate = gate_for_model(report, comparison, prereg, critical_failures=critical_failures)
    rows = []
    for task in report.tasks:
        summary = report.summary.get(task["task_id"], {})
        rows.append({
            "task_id": task["task_id"],
            "brief": task["prompt_brief"],
            "split": task["split"],
            "critical": bool(task.get("critical")),
            "champion": summary.get("champion", {}).get("pass_rate", 0.0),
            "baseline": summary.get(BASELINE_ID, {}).get("pass_rate", 0.0),
        })
    count = max(1, len(comparison["rates_first"]))
    return {
        "report_id": f"eval-{new_patch_id().lower()[:16]}",
        "benchmark": "benchmarks/tasks_m7.jsonl",
        "bench_version": prereg["bench_version"],
        "model": report.model_snapshot,
        "executor": executor_kind,
        "simulated": report.is_simulated,
        "created_at": _now(),
        "candidate": "champion",
        "baseline_id": BASELINE_ID,
        "baseline_label": "开源专家模板基线，非人工盲写基线",
        "label": gate["label"],
        "reason": gate["reason"],
        "mean_diff": gate["mean_diff"],
        "ci": gate["ci"],
        "p_value": gate["p_value"],
        "n_tasks": comparison["n_tasks"],
        "critical_failures": critical_failures,
        "champion_rate": sum(comparison["rates_first"]) / count,
        "baseline_rate": sum(comparison["rates_second"]) / count,
        "rows": rows,
        "source": "backend",
    }


def _public_benchmark(root: Path) -> dict[str, Any]:
    prereg = load_prereg(root / "benchmarks" / "preregistration.json")
    tasks = [
        {
            "task_id": task["task_id"],
            "type": task.get("type", "other"),
            "judge": task.get("judge", "machine"),
            "prompt_brief": task["prompt_brief"],
            "done_criteria": task.get("done_criteria") or [],
            "critical": bool(task.get("critical")),
            "split": task.get("split", "confirmatory"),
        }
        for task in load_bench(root / "benchmarks" / "tasks_m7.jsonl")
    ]
    return {
        "tasks": tasks,
        "preregistration": prereg,
        "hidden": {
            "declared": bool(prereg.get("hidden_path")),
            "content_exposed": False,
            "note": "隐藏集由后端隔离；UI 不请求、不展示、不推断隐藏题目，也不返回 simulation/gold。",
        },
        "source": "backend",
    }


def register_ui_routes(
    app: FastAPI,
    service: ConnectorService,
    context: Callable[[str | None, str | None], Context],
    *,
    project_root: str | Path | None = None,
    config_path: str | Path | None = None,
) -> None:
    root = Path(project_root) if project_root else _DEFAULT_ROOT
    target_config = Path(config_path) if config_path else root / "config.yaml"
    app.state.ui_latest_evaluation = None
    app.state.ui_config_path = target_config

    @app.get("/v1/ui/tasks/{task_id}/rubric")
    def ui_rubric(task_id: str, authorization: str | None = Header(default=None), x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        ctx = context(authorization, x_tenant_id)
        task = service.get_task(ctx, task_id)
        if task.get("rubric"):
            return task["rubric"]
        draft = task.get("draft") or {}
        return build_rubric_draft(str(draft.get("text", "")), draft.get("materials") or [])

    @app.post("/v1/ui/ir/patch")
    def ui_apply_patch(payload: dict[str, Any], authorization: str | None = Header(default=None), x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        ctx = context(authorization, x_tenant_id)
        service._require(ctx, "iterate.v1")
        try:
            base = service._parse_ir(payload.get("ir") or {})
            raw_ops = payload.get("ops") or []
            if not isinstance(raw_ops, list) or not raw_ops:
                raise ServiceError("E_SCHEMA_INVALID", 422, "ops must be a non-empty list")
            reason = str(payload.get("reason") or "UI Patch")
            ops = []
            for index, raw_value in enumerate(raw_ops):
                raw = dict(_require_dict(raw_value, f"ops[{index}]"))
                raw["reason"] = str(raw.get("reason") or reason)
                if raw.get("op") == "DELETE" and not raw.get("evidence_refs"):
                    raise ServiceError("E_SCHEMA_INVALID", 422, "DELETE requires evidence_refs")
                ops.append(raw)
            kinds = {raw.get("op") for raw in ops}
            intent = "simplify" if kinds <= {"DELETE", "MOVE"} else "improve"
            stored = service.conn.execute("SELECT 1 FROM irs WHERE ir_id=?", (base.ir_id,)).fetchone()
            if not stored:
                service.ledger.create_ir(base.payload() | {"checksum": base.checksum})
            current = service.ledger.current(base.ir_id)
            if current.checksum != base.checksum or current.version != base.version:
                raise ServiceError("E_BASE_DRIFT", 409, "base IR is not the current ledger version")
            existing_protect = {row["loc"] for row in service.conn.execute("SELECT loc FROM protect").fetchall()}
            for entry in base.protect_registry:
                if entry.state == "enacted" and entry.loc not in existing_protect:
                    service.ledger.upsert_protect(entry.loc, entry.cls, "enacted", entry.by, entry.review_by)
            patch = Patch.model_validate({
                "schema_version": "3",
                "patch_id": new_patch_id(),
                "base": {"ir_id": base.ir_id, "version": base.version, "checksum": base.checksum},
                "intent": intent,
                "ops": ops,
                "idempotency_key": str(payload.get("idempotency_key") or new_patch_id()),
                "created": {"by": ctx.connector_id, "at": _now(), "source": "local-ui"},
            })
            patch = patch.model_copy(update={"patch_hash": patch.compute_hash()})
            result = service.ledger.apply(patch)
            model = str(payload.get("model") or "generic")
            if model not in service._card_ids():
                raise ServiceError("E_SCHEMA_INVALID", 422, f"unknown model card {model!r}")
            rendered = render(result.ir, model)
            return {
                "patch": patch.model_dump(mode="json", by_alias=True),
                "ir": result.ir.model_dump(mode="json", by_alias=True),
                "rendered": {"text": rendered.text, "cache_key": rendered.cache_key, "model": model},
                "persisted": True,
            }
        except ApplyError as exc:
            status = 409 if "DRIFT" in exc.code or "STALE" in exc.code else 422
            raise ServiceError(exc.code, status, exc.detail) from exc
        except ValidationError as exc:
            raise ServiceError("E_SCHEMA_INVALID", 422, str(exc)[:300]) from exc

    @app.get("/v1/ui/evaluations/latest")
    def ui_latest_evaluation(authorization: str | None = Header(default=None), x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        ctx = context(authorization, x_tenant_id)
        service._require(ctx, "governance.read.v1")
        if app.state.ui_latest_evaluation is None:
            from ..config import primary_target
            app.state.ui_latest_evaluation = _evaluation_report(service.config, root, primary_target(service.config), "scripted")
        return app.state.ui_latest_evaluation

    @app.post("/v1/ui/evaluations/run")
    def ui_run_evaluation(payload: dict[str, Any], authorization: str | None = Header(default=None), x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        ctx = context(authorization, x_tenant_id)
        service._require(ctx, "generate.v1")
        executor = str(payload.get("executor") or "scripted")
        target = str(payload.get("target") or "deepseek")
        if target not in (service.config.get("targets") or {}):
            raise ServiceError("E_SCHEMA_INVALID", 422, f"unknown target {target!r}")
        try:
            result = _evaluation_report(service.config, root, target, executor)
        except (ConfigError, LLMError, ValueError, OSError) as exc:
            raise ServiceError("E_EVALUATION_FAILED", 422, _safe_detail(service.config, exc)) from exc
        app.state.ui_latest_evaluation = result
        return result

    @app.get("/v1/ui/config")
    def ui_get_config(authorization: str | None = Header(default=None), x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        ctx = context(authorization, x_tenant_id)
        service._require(ctx, "governance.read.v1")
        return _public_config(service.config)

    @app.post("/v1/ui/config/check")
    def ui_check_config(payload: dict[str, Any], authorization: str | None = Header(default=None), x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        ctx = context(authorization, x_tenant_id)
        service._require(ctx, "governance.read.v1")
        merged = _merge_ui_config(payload, service.config)
        return _check_result(merged)

    @app.put("/v1/ui/config")
    def ui_save_config(payload: dict[str, Any], authorization: str | None = Header(default=None), x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        ctx = context(authorization, x_tenant_id)
        service._require(ctx, "modelcard.request.v1")
        merged = _merge_ui_config(payload, service.config)
        result = _check_result(merged)
        if not result["ok"]:
            return result
        _write_config(target_config, merged)
        service.config = merged
        app.state.config = merged
        return result

    @app.post("/v1/ui/config/probe")
    def ui_probe(payload: dict[str, Any], authorization: str | None = Header(default=None), x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        ctx = context(authorization, x_tenant_id)
        service._require(ctx, "generate.v1")
        target = str(payload.get("target") or "")
        started = perf_counter()
        try:
            client, _ = build_target_client(service.config, target)
            reply = client.chat([{"role": "user", "content": "ping"}], max_tokens=8, temperature=0.0)
            elapsed = round((perf_counter() - started) * 1000)
            return {"target": target, "ok": True, "latency_ms": elapsed, "detail": f"最小请求成功，响应长度 {len(reply)} 字符。", "checked_at": _now(), "source": "backend"}
        except (ConfigError, LLMError, Exception) as exc:
            elapsed = round((perf_counter() - started) * 1000)
            return {"target": target, "ok": False, "latency_ms": elapsed, "detail": _safe_detail(service.config, exc), "checked_at": _now(), "source": "backend"}

    @app.get("/v1/ui/sessions/{session_id}/replay")
    def ui_session_replay(session_id: str, authorization: str | None = Header(default=None), x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        ctx = context(authorization, x_tenant_id)
        session = service.get_session(ctx, session_id)
        turns = service.sessions.turns(session_id)
        events = [
            {
                "event_seq": event["event_seq"],
                "event_type": event["type"],
                "state": event["state"],
                "attempts": event["attempts"],
                "payload": event["payload"],
                "created_at": None,
            }
            for event in pull(service.conn, session_id, after_seq=0, limit=1000)
        ]
        suggestions = []
        rows = service.conn.execute("SELECT * FROM suggestions WHERE session_id=? ORDER BY created_at", (session_id,)).fetchall()
        for row in rows:
            patch = json.loads(row["patch_json"])
            ops = patch.get("ops") or []
            first = ops[0] if ops else {}
            summary = str(first.get("reason") or f"{first.get('op', 'PATCH')} {first.get('loc', '')}")
            if len(ops) > 1:
                summary = f"{summary} 等 {len(ops)} 项修改"
            suggestions.append({
                "suggestion_id": row["suggestion_id"],
                "state": row["state"],
                "summary": summary,
                "epoch": row["epoch"],
                "base_checksum": row["base_checksum"],
                "created_at": row["created_at"],
            })
        return {"session": session, "turns": turns, "events": events, "suggestions": suggestions, "source": "backend"}

    @app.get("/v1/ui/benchmark")
    def ui_benchmark(authorization: str | None = Header(default=None), x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        ctx = context(authorization, x_tenant_id)
        service._require(ctx, "governance.read.v1")
        try:
            return _public_benchmark(root)
        except (OSError, ValueError) as exc:
            raise ServiceError("E_BENCHMARK_UNAVAILABLE", 500, str(exc)[:200]) from exc
