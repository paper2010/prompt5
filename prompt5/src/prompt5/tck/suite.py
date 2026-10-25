"""TCK：连接器契约测试套件（HTTP + MCP + 安全基线）。

运行：`python -m prompt5.tck [--config config.example.yaml] [--quiet]`
退出码：0 全绿；1 存在失败。
"""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path
from typing import Any, Callable

from fastapi.testclient import TestClient

from ..config import load_config
from ..connector.api import build_connector_app
from ..connector.mcp_adapter import call_tool, list_tools
from ..engine.iterate import propose_patch
from ..modules.m1_extractor import extract_rules
from ..modules.m4_generator import generate_from_frame
from ..security.signing import SigningError, sign_event, verify_event
from ..security.ssrf import SSRFError, validate_callback_url

Auth = dict[str, str]
AUTH_A: Auth = {"Authorization": "Bearer host-agent-alpha"}
AUTH_NARROW: Auth = {"Authorization": "Bearer narrow"}
AUTH_OTHER: Auth = {"Authorization": "Bearer other-tenant"}


def _task_payload(key: str = "idem-1", text: str = "把这份 CSV 做成分析报告") -> dict[str, Any]:
    return {
        "api_version": "1",
        "request_id": f"req-{key}",
        "idempotency_key": key,
        "connector_id": "host-agent-alpha",
        "tenant_id": "t-001",
        "op": "generate.v1",
        "input": {
            "mode": "zero",
            "dialogue": [{"turn": 1, "role": "user", "text": text}],
            "materials": [],
            "target_model": "deepseek",
            "rubric_policy": "draft_then_confirm",
        },
    }


class Suite:
    def __init__(self, config_path: str | Path) -> None:
        base = load_config(config_path).data
        config = copy.deepcopy(base)
        config["connectors"] = list(base.get("connectors") or []) + [
            {"id": "narrow", "tenant_id": "t-001", "enabled": True, "scopes": ["discovery.v1"]},
            {"id": "other-tenant", "tenant_id": "t-002", "enabled": True,
             "scopes": ["generate.v1", "render.v1", "governance.read.v1"]},
        ]
        self.blob_root = Path(tempfile.mkdtemp()) / "blobs"
        self.app = build_connector_app(config, db_path=":memory:", blob_root=self.blob_root)
        self.client = TestClient(self.app)
        self.service = self.app.state.service
        self.results: list[tuple[str, bool, str]] = []
        self.state: dict[str, Any] = {}

    # ---------------------------------------------------------------- helpers
    def check(self, name: str, fn: Callable[[], None]) -> None:
        try:
            fn()
        except AssertionError as exc:
            self.results.append((name, False, str(exc) or "assertion failed"))
        except Exception as exc:  # noqa: BLE001 - TCK 需要把所有异常记为失败
            self.results.append((name, False, f"{type(exc).__name__}: {exc}"))
        else:
            self.results.append((name, True, ""))

    def json(self, response) -> dict[str, Any]:
        assert response.headers.get("content-type", "").startswith("application/json"), (
            f"unexpected content-type: {response.headers.get('content-type')}"
        )
        return response.json()

    # ---------------------------------------------------------------- cases
    def discovery(self) -> None:
        response = self.client.get("/v1/capabilities", headers=AUTH_A)
        assert response.status_code == 200, response.text
        body = self.json(response)
        assert len(body["capabilities"]) == 9

        schema = self.json(self.client.get("/v1/schema", headers=AUTH_A))
        assert set(schema) == {"ir.v3", "patch.v3", "task_request.v1", "eval_evidence.v1"}

        cards = self.json(self.client.get("/v1/model-cards", headers=AUTH_A))["model_cards"]
        assert len(cards) == 6
        assert sum(1 for card in cards if card["primary"]) == 1
        assert any(card["target"] == "deepseek" and card["primary"] for card in cards)

        budget = self.json(self.client.get("/v1/budget", headers=AUTH_A))
        assert "limits" in budget and "used" in budget

    def auth(self) -> None:
        assert self.client.get("/v1/capabilities").status_code == 401
        assert self.client.get("/v1/capabilities", headers={"Authorization": "Bearer nope"}).status_code == 401
        mismatch = self.client.get(
            "/v1/capabilities", headers={**AUTH_A, "X-Tenant-Id": "t-999"}
        )
        assert mismatch.status_code == 401
        assert mismatch.json()["error_code"] == "E_AUTH_IDENTITY_MISMATCH"

    def scope(self) -> None:
        response = self.client.post("/v1/tasks", json=_task_payload("scope-1"), headers=AUTH_NARROW)
        assert response.status_code == 403
        assert response.json()["error_code"] == "E_SCOPE"

    def generate(self) -> None:
        response = self.client.post("/v1/tasks", json=_task_payload("gen-1"), headers=AUTH_A)
        assert response.status_code == 202, response.text
        body = self.json(response)
        assert body["task_id"].startswith("tk-")
        assert body["state"] == "rubric_pending", "rubric 人工锚点不得被绕过"
        self.state["task_id"] = body["task_id"]

        pending = self.json(self.client.get(f"/v1/tasks/{body['task_id']}", headers=AUTH_A))
        assert pending["state"] == "rubric_pending"

        confirmed = self.client.post(f"/v1/tasks/{body['task_id']}/rubric:confirm", headers=AUTH_A)
        assert confirmed.status_code == 200, confirmed.text

        task = self.json(self.client.get(f"/v1/tasks/{body['task_id']}", headers=AUTH_A))
        assert task["state"] == "succeeded"
        assert task["ir"]["checksum"] and task["rendered"]["text"].startswith("# 角色")
        assert task["l1"]["passed"] is True
        self.state["ir"] = task["ir"]

        evidence = self.json(self.client.get(f"/v1/tasks/{body['task_id']}/evidence", headers=AUTH_A))
        assert evidence["reproduction_tier"] == "T2"
        assert evidence["renderer_version"]

        cancelled = self.client.post(f"/v1/tasks/{body['task_id']}/cancel", headers=AUTH_A)
        assert cancelled.status_code == 409
        assert cancelled.json()["error_code"] == "E_FENCING_STALE"

    def idempotency(self) -> None:
        payload = _task_payload("idem-1")
        first = self.client.post("/v1/tasks", json=payload, headers=AUTH_A)
        assert first.status_code == 202
        assert self.json(first)["state"] == "rubric_pending"
        task_id = self.json(first)["task_id"]

        replay = self.client.post("/v1/tasks", json=payload, headers=AUTH_A)
        assert replay.status_code == 202
        assert replay.headers.get("X-Idem") == "replay"
        assert self.json(replay)["task_id"] == task_id

        changed = _task_payload("idem-1", text="另一个完全不同的任务")
        conflict = self.client.post("/v1/tasks", json=changed, headers=AUTH_A)
        assert conflict.status_code == 409
        assert conflict.json()["error_code"] == "E_IDEM_PAYLOAD_MISMATCH"

    def blobs(self) -> None:
        upload = self.client.post(
            "/v1/blobs", content=b"col\n1\n",
            headers={**AUTH_A, "X-Blob-Mime": "text/csv"},
        )
        assert upload.status_code == 200, upload.text
        meta = self.json(upload)
        download = self.client.get(f"/v1/blobs/{meta['blob_id']}", headers=AUTH_A)
        assert download.status_code == 200 and download.content == b"col\n1\n"

        cross = self.client.get(f"/v1/blobs/{meta['blob_id']}", headers=AUTH_OTHER)
        assert cross.status_code == 403

        bad_mime = self.client.post(
            "/v1/blobs", content=b"x", headers={**AUTH_A, "X-Blob-Mime": "video/mp4"}
        )
        assert bad_mime.status_code == 415

    def sync_ops(self) -> None:
        ir = self.state["ir"]
        scored = self.client.post("/v1/score", json={"ir": ir, "rendered_text": "x"}, headers=AUTH_A)
        assert scored.status_code == 200, scored.text
        assert "passed" in self.json(scored)

        tampered = dict(ir)
        tampered["checksum"] = "0" * 64
        bad = self.client.post("/v1/score", json={"ir": tampered}, headers=AUTH_A)
        assert bad.status_code == 422 and bad.json()["error_code"] == "E_SCHEMA_INVALID"

        rendered = self.client.post("/v1/render", json={"ir": ir, "model": "deepseek"}, headers=AUTH_A)
        assert rendered.status_code == 200
        assert "# 目标" in self.json(rendered)["text"]

    def sessions(self) -> None:
        seed_ir = generate_from_frame(extract_rules("把这份 CSV 做成分析报告"))
        stored = self.service.ledger.create_ir(seed_ir.payload() | {"checksum": seed_ir.checksum})

        opened = self.client.post("/v1/sessions", json={"ir_id": stored.ir_id}, headers=AUTH_A)
        assert opened.status_code == 200, opened.text
        session_id = self.json(opened)["session_id"]
        self.state["session_id"] = session_id

        turn = self.client.post(
            f"/v1/sessions/{session_id}/events", json={"text": "好的，谢谢"}, headers=AUTH_A
        )
        assert turn.status_code == 200 and self.json(turn)["seq"] == 1

        events = self.json(self.client.get(f"/v1/sessions/{session_id}/events", headers=AUTH_A))
        assert len(events["events"]) >= 2

        patch = propose_patch(stored, "请用表格输出")
        assert patch is not None
        suggestion = self.service.sessions.propose(session_id, patch, self.service.ledger)
        applied = self.client.post(
            f"/v1/sessions/{session_id}/patches",
            json={
                "suggestion_id": suggestion["suggestion_id"],
                "epoch": suggestion["epoch"],
                "base_checksum": suggestion["base_checksum"],
                "intent_hash": suggestion["intent_hash"],
                "context_hash": suggestion["context_hash"],
            },
            headers=AUTH_A,
        )
        assert applied.status_code == 200, applied.text
        assert self.json(applied)["status"] == "applied"

        replay = self.client.post(
            f"/v1/sessions/{session_id}/patches",
            json={"suggestion_id": suggestion["suggestion_id"], "epoch": suggestion["epoch"],
                  "base_checksum": suggestion["base_checksum"],
                  "intent_hash": suggestion["intent_hash"],
                  "context_hash": suggestion["context_hash"]},
            headers=AUTH_A,
        )
        assert self.json(replay)["status"] == "idempotent"

    def governance(self) -> None:
        protection = self.client.post(
            "/v1/protection-requests",
            json={"loc": "slots.role", "cls": "safety", "reason": "tck"},
            headers=AUTH_A,
        )
        assert protection.status_code == 202
        assert self.json(protection)["state"] == "proposed"

        modelcard = self.client.post(
            "/v1/model-card-requests",
            json={"model_id": "vendor-model-x", "provider": "x", "model": "x-1"},
            headers=AUTH_A,
        )
        assert modelcard.status_code == 202
        assert self.json(modelcard)["state"] == "requested"

    def mcp_registry(self) -> None:
        tools = list_tools()
        assert len(tools) == 18
        names = [tool["name"] for tool in tools]
        assert len(set(names)) == 18
        assert all(tool["capability"] for tool in tools)
        assert {tool["capability"] for tool in tools} == set(
            __import__("prompt5.capabilities", fromlist=["CAPABILITIES"]).CAPABILITIES
        )

        ctx = self.service.authenticate("host-agent-alpha")
        http_caps = self.json(self.client.get("/v1/capabilities", headers=AUTH_A))
        mcp_caps = call_tool("pg_capabilities", {}, self.service, ctx)
        assert mcp_caps == http_caps

        http_cards = self.json(self.client.get("/v1/model-cards", headers=AUTH_A))
        assert call_tool("pg_model_cards", {}, self.service, ctx) == http_cards
        assert call_tool("pg_budget_read", {}, self.service, ctx) == self.json(
            self.client.get("/v1/budget", headers=AUTH_A)
        )

    def mcp_tools_all_callable(self) -> None:
        ctx = self.service.authenticate("host-agent-alpha")
        task_id = self.state["task_id"]
        session_id = self.state["session_id"]
        ir = self.state["ir"]

        call_tool("pg_generate", _task_payload("mcp-1"), self.service, ctx)
        call_tool("pg_iterate", {"seed_text": "# 目标\n做点事\n", "task": "请用表格输出"}, self.service, ctx)
        call_tool("pg_task_status", {"task_id": task_id}, self.service, ctx)
        call_tool("pg_rubric_confirm", {"task_id": task_id}, self.service, ctx)  # 已确认 → 幂等返回
        call_tool("pg_evidence_get", {"task_id": task_id}, self.service, ctx)
        call_tool("pg_score", {"ir": ir}, self.service, ctx)
        call_tool("pg_render", {"ir": ir, "model": "deepseek"}, self.service, ctx)
        call_tool("pg_session_status", {"session_id": session_id}, self.service, ctx)
        call_tool("pg_turn_record", {"session_id": session_id, "text": "进度：已完成"}, self.service, ctx)
        call_tool("pg_protection_request", {"loc": "slots.role", "cls": "hard_format"}, self.service, ctx)
        call_tool("pg_modelcard_request", {"model_id": "vendor-y"}, self.service, ctx)

        try:
            call_tool("pg_task_cancel", {"task_id": task_id}, self.service, ctx)
        except Exception as exc:
            assert getattr(exc, "code", "") == "E_FENCING_STALE", f"unexpected cancel error: {exc}"
        else:
            raise AssertionError("cancel on terminal task should fail")

    def security(self) -> None:
        for bad in (
            "http://127.0.0.1:8080/hook",
            "http://10.0.0.5/hook",
            "http://169.254.169.254/latest/meta-data",
            "file:///etc/passwd",
            "http://localhost/hook",
        ):
            try:
                validate_callback_url(bad)
            except SSRFError:
                continue
            raise AssertionError(f"SSRF guard missed: {bad}")

        event = {"event": "task.state_changed", "data": {"task_id": "tk-1"}}
        signed = sign_event(event, "secret", timestamp=1000)
        assert verify_event(signed, "secret", now=1100) is True
        tampered = {**signed, "data": {"task_id": "tk-2"}}
        try:
            verify_event(tampered, "secret", now=1100)
        except SigningError:
            pass
        else:
            raise AssertionError("tampered signature accepted")
        try:
            verify_event(signed, "secret", now=100000)
        except SigningError:
            pass
        else:
            raise AssertionError("expired timestamp accepted")

    # ---------------------------------------------------------------- runner
    def run(self) -> list[tuple[str, bool, str]]:
        cases = [
            ("discovery: capabilities/schema/model-cards/budget", self.discovery),
            ("auth: missing token / tenant mismatch", self.auth),
            ("scope: narrow connector rejected", self.scope),
            ("generate: task lifecycle + evidence + rubric + terminal cancel", self.generate),
            ("idempotency: replay + payload mismatch", self.idempotency),
            ("blobs: roundtrip + cross-tenant + mime allowlist", self.blobs),
            ("sync: score/render + checksum guard", self.sync_ops),
            ("sessions: turn/events/suggestion apply + idempotent replay", self.sessions),
            ("governance: protection/modelcard requests", self.governance),
            ("mcp: 18 tools registry + HTTP equivalence", self.mcp_registry),
            ("mcp: all tools callable", self.mcp_tools_all_callable),
            ("security: SSRF + signature", self.security),
        ]
        for name, fn in cases:
            self.check(name, fn)
        return self.results


def run(config_path: str | Path = "config.example.yaml", *, verbose: bool = True) -> dict[str, Any]:
    suite = Suite(config_path)
    results = suite.run()
    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    if verbose:
        for name, ok, detail in results:
            print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  → {detail}" if detail else ""))
        print(f"\nsummary: {passed} passed, {failed} failed")
    return {"passed": passed, "failed": failed, "results": results, "ok": failed == 0}
