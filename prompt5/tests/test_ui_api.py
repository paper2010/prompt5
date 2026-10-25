"""本地 UI 薄适配层契约测试。"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from prompt5.config import load_config
from prompt5.connector.api import build_connector_app
from prompt5.ir import IR
from prompt5.testing import make_ir

ROOT = Path(__file__).resolve().parents[1]
AUTH = {"Authorization": "Bearer host-agent-alpha", "X-Tenant-Id": "t-001"}


@pytest.fixture()
def client(tmp_path):
    config = load_config(ROOT / "config.example.yaml").data
    app = build_connector_app(config, project_root=ROOT, config_path=tmp_path / "config.yaml")
    with TestClient(app) as test_client:
        yield test_client


def create_task(client: TestClient, text: str = "把 CSV 做成结论先行的分析报告") -> str:
    suffix = uuid.uuid4().hex
    response = client.post("/v1/tasks", headers=AUTH, json={
        "api_version": "1",
        "request_id": f"r-{suffix}",
        "idempotency_key": f"k-{suffix}",
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
    })
    assert response.status_code == 202, response.text
    return response.json()["task_id"]


def test_rubric_is_explicit_and_cancel_is_consistent(client: TestClient) -> None:
    task_id = create_task(client)
    rubric = client.get(f"/v1/ui/tasks/{task_id}/rubric", headers=AUTH)
    assert rubric.status_code == 200
    assert rubric.json()["source"] == "backend"
    assert rubric.json()["criteria"]
    pending = client.get(f"/v1/tasks/{task_id}", headers=AUTH).json()
    assert pending["state"] == "rubric_pending"
    assert "ir" not in pending

    cancelled = client.post(f"/v1/tasks/{task_id}/cancel", headers=AUTH)
    assert cancelled.status_code == 200
    assert client.get(f"/v1/tasks/{task_id}", headers=AUTH).json()["state"] == "cancelled"
    confirm = client.post(f"/v1/tasks/{task_id}/rubric:confirm", headers=AUTH)
    assert confirm.status_code == 409
    assert confirm.json()["error_code"] == "E_FENCING_STALE"


def test_confirm_uses_same_rubric_version_and_persists_ir(client: TestClient) -> None:
    task_id = create_task(client)
    rubric = client.get(f"/v1/ui/tasks/{task_id}/rubric", headers=AUTH).json()
    assert client.post(f"/v1/tasks/{task_id}/rubric:confirm", headers=AUTH).status_code == 200
    task = client.get(f"/v1/tasks/{task_id}", headers=AUTH).json()
    assert task["state"] == "succeeded"
    assert task["evidence"]["rubric_version"] == rubric["version"]
    assert task["execution"]["kind"] == "mock"
    assert task["ir"]["checksum"]
    current = client.app.state.service.ledger.current(task["ir"]["ir_id"])
    assert current.checksum == task["ir"]["checksum"]


def test_patch_updates_checksum_and_version(client: TestClient) -> None:
    task_id = create_task(client)
    client.post(f"/v1/tasks/{task_id}/rubric:confirm", headers=AUTH)
    before = client.get(f"/v1/tasks/{task_id}", headers=AUTH).json()["ir"]
    response = client.post("/v1/ui/ir/patch", headers=AUTH, json={
        "ir": before,
        "ops": [{"op": "REWRITE", "loc": "slots.role", "content": "严谨的数据分析助手", "reason": "明确角色", "evidence_refs": []}],
        "reason": "明确角色",
        "model": "deepseek",
        "idempotency_key": "ui-patch-1",
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["persisted"] is True
    assert result["ir"]["version"] == before["version"] + 1
    assert result["ir"]["checksum"] != before["checksum"]
    assert result["ir"]["slots"]["role"] == "严谨的数据分析助手"
    assert client.app.state.service.ledger.current(before["ir_id"]).version == before["version"] + 1


def test_patch_enforces_enacted_protection(client: TestClient) -> None:
    raw = make_ir(ir_id="ir-protected-ui-test").model_dump(mode="json", by_alias=True)
    raw["protect_registry"] = [{"loc": "slots.role", "cls": "user_pinned", "state": "enacted", "by": "test"}]
    protected = IR.model_validate(raw).with_checksum()
    response = client.post("/v1/ui/ir/patch", headers=AUTH, json={
        "ir": protected.model_dump(mode="json", by_alias=True),
        "ops": [{"op": "REWRITE", "loc": "slots.role", "content": "绕过保护", "reason": "test", "evidence_refs": []}],
        "model": "deepseek",
        "idempotency_key": "ui-patch-protected",
    })
    assert response.status_code == 422
    assert response.json()["error_code"] == "E_PROTECT_REWRITE"


def test_evaluation_has_required_declarations(client: TestClient) -> None:
    response = client.get("/v1/ui/evaluations/latest", headers=AUTH)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["simulated"] is True
    assert report["executor"] == "scripted"
    assert report["n_tasks"] == 20
    assert len(report["rows"]) == 20
    assert report["baseline_label"] == "开源专家模板基线，非人工盲写基线"
    assert report["label"] in {"optimizing", "compatible", "rejected"}


def test_config_errors_block_write_and_valid_config_saves(client: TestClient) -> None:
    config = client.get("/v1/ui/config", headers=AUTH).json()
    assert "api_key" not in config["providers"]["deepseek"]
    config["providers"]["deepseek"]["base_url"] = ""
    invalid = client.put("/v1/ui/config", headers=AUTH, json=config)
    assert invalid.status_code == 200
    assert invalid.json()["ok"] is False
    assert any(issue["code"] == "CFG_PROVIDER_NO_URL" for issue in invalid.json()["issues"])
    assert not Path(client.app.state.ui_config_path).exists()

    for name, provider in config["providers"].items():
        provider["base_url"] = f"https://{name}.example.test/v1"
        provider["api_key_required"] = False
    valid = client.put("/v1/ui/config", headers=AUTH, json=config)
    assert valid.status_code == 200, valid.text
    assert valid.json()["ok"] is True, valid.json()
    assert Path(client.app.state.ui_config_path).exists()
    assert client.app.state.service.config["providers"]["deepseek"]["base_url"].endswith("/v1")


def test_probe_failure_is_structured(client: TestClient) -> None:
    response = client.post("/v1/ui/config/probe", headers=AUTH, json={"target": "deepseek"})
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["source"] == "backend"
    assert "api_key" not in response.text.lower() or "环境变量" in response.json()["detail"]


def test_session_replay_contains_turns_and_events(client: TestClient) -> None:
    opened = client.post("/v1/sessions", headers=AUTH, json={"ir_id": "ir-replay-test"})
    assert opened.status_code == 200
    session_id = opened.json()["session_id"]
    recorded = client.post(f"/v1/sessions/{session_id}/events", headers=AUTH, json={"text": "谢谢", "role": "user"})
    assert recorded.status_code == 200
    replay = client.get(f"/v1/ui/sessions/{session_id}/replay", headers=AUTH)
    assert replay.status_code == 200
    assert replay.json()["turns"][0]["kind"] == "chitchat"
    assert replay.json()["events"][-1]["event_type"] == "turn.recorded"


def test_benchmark_is_sanitized(client: TestClient) -> None:
    response = client.get("/v1/ui/benchmark", headers=AUTH)
    assert response.status_code == 200
    data = response.json()
    assert len(data["tasks"]) == 30
    assert data["hidden"]["content_exposed"] is False
    for task in data["tasks"]:
        assert "simulation" not in task
        assert "machine_judge" not in task
        assert "model_budget" not in task
