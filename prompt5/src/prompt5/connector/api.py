"""连接器服务层 + HTTP 绑定（MCP 适配器复用同一服务，保证等价性）。

契约（执行方案 §6）：
- 认证主体决定 tenant/connector；正文身份只做一致性核对（不符 → 401）；
- 幂等：`(tenant, connector, op, key)` 唯一 + 载荷哈希；同键异载荷 409；重放返回首次结果；
- 任务异步语义：创建返回 202 + task_id，GET 取结果；终态不可取消（409）；
- 评分/渲染同步；会话事件可拉取；治理请求只提交不批准。
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from ..blobs import BlobError, BlobStore
from ..canonical import sha256_hex
from ..contracts import TaskRequest
from ..engine.flow_zero import run_zero
from ..ids import new_patch_id
from ..ir import IR
from ..ledger import Ledger
from ..llm.client import MockLLM
from ..modules.m3_cards import RENDERER_VERSION, render
from ..modules.m5_eval.l1_rules import check as l1_check
from ..modules.m6_sessions import SessionError, SessionStore
from .rubric import build_rubric_draft

__all__ = ["ServiceError", "Context", "ConnectorService", "build_connector_app"]


class ServiceError(Exception):
    def __init__(self, code: str, status: int, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}".strip())
        self.code = code
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class Context:
    connector_id: str
    tenant_id: str
    scopes: frozenset[str]


class ConnectorService:
    def __init__(self, config: dict[str, Any], *, db_path: str = ":memory:",
                 blob_root: str | Path | None = None) -> None:
        from ..store.migrate import init_db

        self.config = config
        self.conn = init_db(db_path, check_same_thread=False)
        self.ledger = Ledger(self.conn)
        self.sessions = SessionStore(self.conn)
        self.blobs = BlobStore(
            self.conn,
            Path(blob_root) if blob_root else Path(tempfile.mkdtemp()) / "blobs",
        )
        self.llm = MockLLM()  # P0：连接器默认走确定性 Mock；真实生成在 live 模式单独启用

    # ---------------------------------------------------------------- auth
    def authenticate(self, token: str | None, tenant_header: str | None = None) -> Context:
        if not token:
            raise ServiceError("E_AUTH", 401, "missing bearer token")
        for raw in (self.config.get("connectors") or []):
            raw = raw or {}
            expected = raw.get("token") or raw.get("id")
            if token == expected and raw.get("enabled", True):
                tenant = str(raw.get("tenant_id", ""))
                if tenant_header and tenant_header != tenant:
                    raise ServiceError("E_AUTH_IDENTITY_MISMATCH", 401, "tenant header mismatch")
                return Context(
                    connector_id=str(raw.get("id")),
                    tenant_id=tenant,
                    scopes=frozenset(raw.get("scopes") or []),
                )
        raise ServiceError("E_AUTH", 401, "unknown token")

    @staticmethod
    def _require(ctx: Context, scope: str) -> None:
        if scope not in ctx.scopes:
            raise ServiceError("E_SCOPE", 403, f"scope {scope!r} required")

    # ---------------------------------------------------------------- discovery
    def capabilities(self, ctx: Context) -> dict[str, Any]:
        from ..capabilities import CAPABILITIES

        return {
            "api_version": "1",
            "capabilities": [
                {"op": op, "version": "1",
                 "status": "stable" if op in ctx.scopes else "unauthorized",
                 "ready": meta["ready"], "sync": meta["sync"]}
                for op, meta in CAPABILITIES.items()
            ],
        }

    def schemas(self, ctx: Context) -> dict[str, Any]:
        from ..contracts import EvalEvidence, TaskRequest
        from ..ir import IR as IRModel
        from ..patch import Patch

        return {
            "ir.v3": IRModel.model_json_schema(),
            "patch.v3": Patch.model_json_schema(),
            "task_request.v1": TaskRequest.model_json_schema(),
            "eval_evidence.v1": EvalEvidence.model_json_schema(),
        }

    def _card_ids(self) -> set[str]:
        return set((self.config.get("targets") or {}).keys()) | {"generic"}

    def model_cards(self, ctx: Context) -> dict[str, Any]:
        cards = []
        for name, raw in (self.config.get("targets") or {}).items():
            raw = raw or {}
            cards.append({
                "target": name,
                "provider": raw.get("provider"),
                "model": raw.get("model"),
                "tier": raw.get("tier"),
                "label": raw.get("label"),
                "primary": bool(raw.get("primary")),
            })
        return {"model_cards": cards}

    def budget(self, ctx: Context) -> dict[str, Any]:
        limits = self.config.get("budgets") or {}
        used = self.conn.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE connector_id=?", (ctx.connector_id,)
        ).fetchone()["n"]
        return {"limits": limits, "used": {"tasks": int(used)}}

    # ---------------------------------------------------------------- tasks
    def create_task(self, ctx: Context, payload: dict[str, Any]) -> tuple[int, dict[str, Any], bool]:
        self._require(ctx, "generate.v1")
        try:
            request = TaskRequest.model_validate(payload)
        except Exception as exc:  # pydantic 校验失败统一 422
            raise ServiceError("E_SCHEMA_INVALID", 422, str(exc)[:200]) from exc

        if request.tenant_id != ctx.tenant_id or request.connector_id != ctx.connector_id:
            raise ServiceError("E_AUTH_IDENTITY_MISMATCH", 401, "body identity mismatch")

        request_hash = sha256_hex(request.model_dump(mode="json"))
        row = self.conn.execute(
            "SELECT * FROM idempotency WHERE connector_id=? AND tenant_id=? AND op=? AND key=?",
            (ctx.connector_id, ctx.tenant_id, request.op, request.idempotency_key),
        ).fetchone()
        if row is not None:
            if row["request_hash"] != request_hash:
                raise ServiceError("E_IDEM_PAYLOAD_MISMATCH", 409, "same key, different payload")
            return int(row["response_code"]), json.loads(row["response_json"]), True

        text = next(
            (turn.text for turn in reversed(request.input.dialogue) if turn.role == "user"),
            "",
        )
        if not text:
            raise ServiceError("E_SCHEMA_INVALID", 422, "dialogue requires a user turn")

        model_id = request.input.target_model or "generic"
        if model_id not in self._card_ids():
            raise ServiceError("E_SCHEMA_INVALID", 422, f"unknown model card {model_id!r}")

        task_id = f"tk-{new_patch_id().lower()[:16]}"
        materials = [item.model_dump(mode="json") for item in request.input.materials]
        rubric = build_rubric_draft(text, materials)
        # 人工锚点不可绕过：先进入 rubric_pending，确认后才真正生成
        envelope = {
            "task_id": task_id,
            "tenant_id": ctx.tenant_id,
            "connector_id": ctx.connector_id,
            "state": "rubric_pending",
            "result_class": "pending",
            "model": model_id,
            "draft": {"text": text, "rubric_policy": request.input.rubric_policy,
                      "materials": materials},
            "rubric": rubric,
        }
        self.conn.execute(
            "INSERT INTO tasks(task_id, connector_id, op, state, stage, result_class,"
            " fencing_token, envelope_json, rubric_state, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, ctx.connector_id, request.op, "rubric_pending", "awaiting_rubric",
             "pending", 0, json.dumps(envelope, ensure_ascii=False), "pending", "now", "now"),
        )
        body = {"task_id": task_id, "state": "rubric_pending", "result_class": "pending",
                "model": model_id}
        self.conn.execute(
            "INSERT INTO idempotency(connector_id, tenant_id, op, key, request_hash,"
            " response_code, response_json, created_at, expires_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (ctx.connector_id, ctx.tenant_id, request.op, request.idempotency_key,
             request_hash, 202, json.dumps(body, ensure_ascii=False), "now", "later"),
        )
        return 202, body, False

    def _load_task(self, ctx: Context, task_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise ServiceError("E_FIELD_UNKNOWN", 404, f"task {task_id} not found")
        envelope = json.loads(row["envelope_json"])
        if envelope.get("tenant_id") != ctx.tenant_id:
            raise ServiceError("E_SCOPE", 403, "cross-tenant task access")
        return {"row": row, "envelope": envelope}

    def get_task(self, ctx: Context, task_id: str) -> dict[str, Any]:
        self._require(ctx, "generate.v1")
        data = self._load_task(ctx, task_id)
        return data["envelope"]

    def cancel_task(self, ctx: Context, task_id: str) -> dict[str, Any]:
        self._require(ctx, "generate.v1")
        data = self._load_task(ctx, task_id)
        state = data["envelope"]["state"]
        if state in {"succeeded", "failed", "cancelled"}:
            raise ServiceError("E_FENCING_STALE", 409, f"task already {state}")
        envelope = data["envelope"]
        envelope.update({"state": "cancelled", "stage": "cancelled", "result_class": "pending"})
        self.conn.execute(
            "UPDATE tasks SET state='cancelled', stage='cancelled', envelope_json=?,"
            " updated_at='now' WHERE task_id=?",
            (json.dumps(envelope, ensure_ascii=False), task_id),
        )
        return {"task_id": task_id, "state": "cancelled"}

    def confirm_rubric(self, ctx: Context, task_id: str) -> dict[str, Any]:
        self._require(ctx, "generate.v1")
        data = self._load_task(ctx, task_id)
        if data["envelope"]["state"] == "succeeded":
            return {"task_id": task_id, "state": "succeeded", "rubric_state": "confirmed"}
        if data["envelope"]["state"] != "rubric_pending":
            raise ServiceError("E_FENCING_STALE", 409, "task is not awaiting rubric")

        envelope = data["envelope"]
        model_id = envelope["model"]
        text = envelope["draft"]["text"]
        materials = envelope["draft"].get("materials", [])
        result = run_zero(text, llm=self.llm, model_id=model_id, materials=materials)
        evidence = {
            "level": "L1",
            "rubric_version": envelope.get("rubric", {}).get("version", "confirmed-v1"),
            "metrics": {},
            "reproduction_tier": "T2",
            "model_snapshot": f"{model_id}@mock",
            "decode": {"temperature": 0.0},
            "renderer_version": RENDERER_VERSION,
            "baseline_id": None,
            "label": None,
            "expires_at": None,
        }
        exists = self.conn.execute("SELECT 1 FROM irs WHERE ir_id=?", (result.ir.ir_id,)).fetchone()
        if not exists:
            self.ledger.create_ir(result.ir.payload() | {"checksum": result.ir.checksum})
        envelope.update(
            {
                "state": "succeeded",
                "result_class": "full",
                "ir": result.ir.model_dump(mode="json", by_alias=True),
                "rendered": {"text": result.rendered.text, "cache_key": result.rendered.cache_key},
                "l1": result.l1.to_dict(),
                "evidence": evidence,
                "execution": {"kind": "mock", "label": "Mock 生成 · 不代表目标模型真实输出"},
                "rubric_state": "confirmed",
            }
        )
        self.conn.execute(
            "UPDATE tasks SET state='succeeded', stage='done', result_class='full',"
            " rubric_state='confirmed', envelope_json=?, updated_at='now' WHERE task_id=?",
            (json.dumps(envelope, ensure_ascii=False), task_id),
        )
        return {"task_id": task_id, "state": "succeeded", "rubric_state": "confirmed"}

    def evidence(self, ctx: Context, task_id: str) -> dict[str, Any]:
        self._require(ctx, "governance.read.v1")
        envelope = self._load_task(ctx, task_id)["envelope"]
        if "evidence" not in envelope:
            raise ServiceError("E_FENCING_STALE", 409, "task evidence is not ready")
        return envelope["evidence"]

    # ---------------------------------------------------------------- sync ops
    def _parse_ir(self, payload: dict[str, Any]) -> IR:
        try:
            ir = IR.model_validate(payload)
        except Exception as exc:
            raise ServiceError("E_SCHEMA_INVALID", 422, str(exc)[:200]) from exc
        if not ir.verify_checksum():
            raise ServiceError("E_SCHEMA_INVALID", 422, "ir checksum mismatch")
        return ir

    def score(self, ctx: Context, payload: dict[str, Any]) -> dict[str, Any]:
        self._require(ctx, "score.v1")
        ir = self._parse_ir(payload.get("ir") or {})
        report = l1_check(ir, str(payload.get("rendered_text", "")))
        return report.to_dict()

    def render(self, ctx: Context, payload: dict[str, Any]) -> dict[str, Any]:
        self._require(ctx, "render.v1")
        ir = self._parse_ir(payload.get("ir") or {})
        model_id = str(payload.get("model") or "generic")
        try:
            result = render(ir, model_id)
        except KeyError as exc:
            raise ServiceError("E_SCHEMA_INVALID", 422, f"unknown model card {model_id!r}") from exc
        return {"text": result.text, "cache_key": result.cache_key, "model": model_id}

    def iterate(self, ctx: Context, payload: dict[str, Any]) -> dict[str, Any]:
        """种子迭代（P0 简化：同步执行并返回最终 IR）。"""
        self._require(ctx, "iterate.v1")
        from ..engine.iterate import run_iterate
        from ..modules.m1_seed import parse_seed_prompt

        seed_text = str(payload.get("seed_text") or "")
        if not seed_text:
            raise ServiceError("E_SCHEMA_INVALID", 422, "seed_text required")
        seed_ir = parse_seed_prompt(seed_text)
        stored = self.ledger.create_ir(seed_ir.payload() | {"checksum": seed_ir.checksum})
        outcome = run_iterate(
            stored, str(payload.get("task") or ""), self.ledger,
            max_rounds=int(payload.get("max_rounds", 1)),
        )
        return {
            "ir_id": stored.ir_id,
            "state": "succeeded",
            "applied": [patch.patch_id for patch in outcome.applied],
            "rejected": outcome.rejected,
            "ir_version": outcome.final_ir.version,
            "ir": outcome.final_ir.model_dump(mode="json", by_alias=True),
        }

    # ---------------------------------------------------------------- sessions
    def open_session(self, ctx: Context, payload: dict[str, Any]) -> dict[str, Any]:
        self._require(ctx, "events.v1")
        ir_id = str(payload.get("ir_id") or "")
        if not ir_id:
            raise ServiceError("E_SCHEMA_INVALID", 422, "ir_id required")
        return self.sessions.open(ir_id)

    def get_session(self, ctx: Context, session_id: str) -> dict[str, Any]:
        self._require(ctx, "governance.read.v1")
        try:
            return self.sessions.get(session_id)
        except SessionError as exc:
            raise ServiceError(exc.code, exc.status, exc.detail) from exc

    def record_turn(self, ctx: Context, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require(ctx, "events.v1")
        try:
            return self.sessions.record_turn(
                session_id, str(payload.get("text", "")),
                role=str(payload.get("role", "user")),
                seq=payload.get("seq"),
            )
        except SessionError as exc:
            raise ServiceError(exc.code, exc.status, exc.detail) from exc

    def pull_events(self, ctx: Context, session_id: str, after_seq: int = 0) -> dict[str, Any]:
        self._require(ctx, "governance.read.v1")
        from ..modules.m6_events import pull

        return {"events": pull(self.conn, session_id, after_seq=after_seq)}

    def apply_patch(self, ctx: Context, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require(ctx, "events.v1")
        try:
            return self.sessions.apply(
                session_id,
                str(payload.get("suggestion_id", "")),
                epoch=int(payload.get("epoch", -1)),
                base_checksum=str(payload.get("base_checksum", "")),
                intent_hash=str(payload.get("intent_hash", "")),
                context_hash=str(payload.get("context_hash", "")),
                ledger=self.ledger,
                fencing_token=payload.get("fencing_token"),
            )
        except SessionError as exc:
            raise ServiceError(exc.code, exc.status, exc.detail) from exc

    # ---------------------------------------------------------------- governance
    def request_protection(self, ctx: Context, payload: dict[str, Any]) -> dict[str, Any]:
        self._require(ctx, "protection.request.v1")
        loc = str(payload.get("loc") or "")
        cls = str(payload.get("cls") or "")
        if not loc or cls not in {"safety", "hard_format", "user_pinned"}:
            raise ServiceError("E_SCHEMA_INVALID", 422, "loc/cls invalid")
        self.conn.execute(
            "INSERT INTO protect(loc, cls, state, by, at, review_by) VALUES(?,?,?,?,?,?)"
            " ON CONFLICT(loc) DO UPDATE SET cls=excluded.cls, state='proposed'",
            (loc, cls, "proposed", ctx.connector_id, "now", ""),
        )
        return {"loc": loc, "state": "proposed"}

    def request_model_card(self, ctx: Context, payload: dict[str, Any]) -> dict[str, Any]:
        self._require(ctx, "modelcard.request.v1")
        model_id = str(payload.get("model_id") or "")
        if not model_id:
            raise ServiceError("E_SCHEMA_INVALID", 422, "model_id required")
        self.conn.execute(
            "INSERT INTO model_cards(model_id, card_hash, card_json, label, bench_version,"
            " evidence_id, achieved_at, expires_at) VALUES(?,?,?,?,?,?,?,?)"
            " ON CONFLICT(model_id) DO UPDATE SET card_json=excluded.card_json",
            (model_id, "requested", json.dumps(payload, ensure_ascii=False), None, "", "", "now", ""),
        )
        return {"model_id": model_id, "state": "requested"}


# ---------------------------------------------------------------- HTTP binding
def build_connector_app(config: dict[str, Any], *, db_path: str = ":memory:",
                        blob_root: str | Path | None = None,
                        project_root: str | Path | None = None,
                        config_path: str | Path | None = None) -> FastAPI:
    service = ConnectorService(config, db_path=db_path, blob_root=blob_root)
    app = FastAPI(title="prompt5-connector", version="1.0.0")
    app.state.service = service
    app.state.config = config
    ui_options = config.get("ui") or {}
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ui_options.get("cors_origins") or [
            "http://127.0.0.1:5173", "http://localhost:5173",
            "http://127.0.0.1:4173", "http://localhost:4173",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Tenant-Id", "X-Blob-Mime"],
    )

    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(
            {"error_code": exc.code, "detail": exc.detail}, status_code=exc.status
        )

    def context(authorization: str | None = Header(default=None),
                x_tenant_id: str | None = Header(default=None)) -> Context:
        token = None
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        return service.authenticate(token, x_tenant_id)

    def ctx_from_headers(authorization: str | None, x_tenant_id: str | None) -> Context:
        return context(authorization, x_tenant_id)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/capabilities")
    def capabilities(authorization: str | None = Header(default=None),
                     x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return service.capabilities(ctx_from_headers(authorization, x_tenant_id))

    @app.get("/v1/schema")
    def schemas(authorization: str | None = Header(default=None),
                x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return service.schemas(ctx_from_headers(authorization, x_tenant_id))

    @app.get("/v1/model-cards")
    def model_cards(authorization: str | None = Header(default=None),
                    x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return service.model_cards(ctx_from_headers(authorization, x_tenant_id))

    @app.get("/v1/budget")
    def budget(authorization: str | None = Header(default=None),
               x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return service.budget(ctx_from_headers(authorization, x_tenant_id))

    @app.post("/v1/blobs")
    async def upload_blob(request: Request,
                          authorization: str | None = Header(default=None),
                          x_tenant_id: str | None = Header(default=None),
                          x_blob_mime: str | None = Header(default=None)):
        ctx = ctx_from_headers(authorization, x_tenant_id)
        body = await request.body()
        try:
            meta = service.blobs.put(ctx.tenant_id, body, x_blob_mime or "application/octet-stream")
        except BlobError as exc:
            raise ServiceError(exc.code, exc.status, exc.detail) from exc
        return {"blob_id": meta.blob_id, "content_hash": meta.sha256, "size": meta.size,
                "mime": meta.mime, "expires_at": meta.expires_at}

    @app.get("/v1/blobs/{blob_id}")
    def download_blob(blob_id: str,
                      authorization: str | None = Header(default=None),
                      x_tenant_id: str | None = Header(default=None)):
        ctx = ctx_from_headers(authorization, x_tenant_id)
        try:
            meta, content = service.blobs.get(ctx.tenant_id, blob_id)
        except BlobError as exc:
            raise ServiceError(exc.code, exc.status, exc.detail) from exc
        return Response(content=content, media_type=meta.mime)

    @app.post("/v1/tasks", status_code=202)
    def create_task(payload: dict[str, Any],
                    authorization: str | None = Header(default=None),
                    x_tenant_id: str | None = Header(default=None)):
        ctx = ctx_from_headers(authorization, x_tenant_id)
        status, body, replay = service.create_task(ctx, payload)
        headers = {"X-Idem": "replay"} if replay else {}
        return JSONResponse(body, status_code=status, headers=headers)

    @app.get("/v1/tasks/{task_id}")
    def get_task(task_id: str,
                 authorization: str | None = Header(default=None),
                 x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return service.get_task(ctx_from_headers(authorization, x_tenant_id), task_id)

    @app.post("/v1/tasks/{task_id}/cancel")
    def cancel_task(task_id: str,
                    authorization: str | None = Header(default=None),
                    x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return service.cancel_task(ctx_from_headers(authorization, x_tenant_id), task_id)

    @app.post("/v1/tasks/{task_id}/rubric:confirm")
    def rubric_confirm(task_id: str,
                       authorization: str | None = Header(default=None),
                       x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return service.confirm_rubric(ctx_from_headers(authorization, x_tenant_id), task_id)

    @app.get("/v1/tasks/{task_id}/evidence")
    def evidence(task_id: str,
                 authorization: str | None = Header(default=None),
                 x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return service.evidence(ctx_from_headers(authorization, x_tenant_id), task_id)

    @app.post("/v1/score")
    def score(payload: dict[str, Any],
              authorization: str | None = Header(default=None),
              x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return service.score(ctx_from_headers(authorization, x_tenant_id), payload)

    @app.post("/v1/render")
    def render_route(payload: dict[str, Any],
                     authorization: str | None = Header(default=None),
                     x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return service.render(ctx_from_headers(authorization, x_tenant_id), payload)

    @app.post("/v1/sessions")
    def open_session(payload: dict[str, Any],
                     authorization: str | None = Header(default=None),
                     x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return service.open_session(ctx_from_headers(authorization, x_tenant_id), payload)

    @app.get("/v1/sessions/{session_id}")
    def get_session(session_id: str,
                    authorization: str | None = Header(default=None),
                    x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return service.get_session(ctx_from_headers(authorization, x_tenant_id), session_id)

    @app.post("/v1/sessions/{session_id}/events")
    def record_turn(session_id: str, payload: dict[str, Any],
                    authorization: str | None = Header(default=None),
                    x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return service.record_turn(ctx_from_headers(authorization, x_tenant_id), session_id, payload)

    @app.get("/v1/sessions/{session_id}/events")
    def pull_events(session_id: str, after_event_seq: int = 0,
                    authorization: str | None = Header(default=None),
                    x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return service.pull_events(ctx_from_headers(authorization, x_tenant_id),
                                   session_id, after_seq=after_event_seq)

    @app.post("/v1/sessions/{session_id}/patches")
    def apply_patch(session_id: str, payload: dict[str, Any],
                    authorization: str | None = Header(default=None),
                    x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return service.apply_patch(ctx_from_headers(authorization, x_tenant_id), session_id, payload)

    @app.post("/v1/protection-requests", status_code=202)
    def protection_request(payload: dict[str, Any],
                           authorization: str | None = Header(default=None),
                           x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return service.request_protection(ctx_from_headers(authorization, x_tenant_id), payload)

    @app.post("/v1/model-card-requests", status_code=202)
    def modelcard_request(payload: dict[str, Any],
                          authorization: str | None = Header(default=None),
                          x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return service.request_model_card(ctx_from_headers(authorization, x_tenant_id), payload)

    from .ui_api import register_ui_routes
    register_ui_routes(
        app, service, ctx_from_headers,
        project_root=project_root, config_path=config_path,
    )
    return app
