"""M6 · 连接器服务与 MCP 注册表（HTTP 行为由 TCK 覆盖）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from prompt5.config import load_config
from prompt5.connector.api import ConnectorService, ServiceError
from prompt5.connector.mcp_adapter import call_tool, list_tools

CONFIG = Path(__file__).resolve().parents[1] / "config.example.yaml"


@pytest.fixture()
def service():
    config = load_config(CONFIG).data
    config["connectors"] = list(config["connectors"]) + [
        {"id": "narrow", "tenant_id": "t-001", "enabled": True, "scopes": ["discovery.v1"]}
    ]
    return ConnectorService(config)


class TestAuth:
    def test_ok(self, service) -> None:
        ctx = service.authenticate("host-agent-alpha")
        assert ctx.tenant_id == "t-001"
        assert "generate.v1" in ctx.scopes

    def test_missing_token(self, service) -> None:
        with pytest.raises(ServiceError) as excinfo:
            service.authenticate(None)
        assert excinfo.value.code == "E_AUTH"

    def test_tenant_mismatch(self, service) -> None:
        with pytest.raises(ServiceError) as excinfo:
            service.authenticate("host-agent-alpha", "t-999")
        assert excinfo.value.code == "E_AUTH_IDENTITY_MISMATCH"

    def test_unknown_token(self, service) -> None:
        with pytest.raises(ServiceError):
            service.authenticate("ghost")

    def test_scope_enforced(self, service) -> None:
        ctx = service.authenticate("narrow")
        with pytest.raises(ServiceError) as excinfo:
            service.create_task(ctx, {})
        assert excinfo.value.code == "E_SCOPE"


class TestTaskValidation:
    def test_body_identity_mismatch(self, service) -> None:
        ctx = service.authenticate("host-agent-alpha")
        payload = {
            "api_version": "1", "request_id": "r", "idempotency_key": "k",
            "connector_id": "host-agent-alpha", "tenant_id": "t-666",
            "op": "generate.v1",
            "input": {"mode": "zero", "dialogue": [], "target_model": "deepseek"},
        }
        with pytest.raises(ServiceError) as excinfo:
            service.create_task(ctx, payload)
        assert excinfo.value.code == "E_AUTH_IDENTITY_MISMATCH"

    def test_unknown_model_card(self, service) -> None:
        ctx = service.authenticate("host-agent-alpha")
        payload = {
            "api_version": "1", "request_id": "r", "idempotency_key": "k2",
            "connector_id": "host-agent-alpha", "tenant_id": "t-001",
            "op": "generate.v1",
            "input": {"mode": "zero", "dialogue": [{"turn": 1, "role": "user", "text": "x"}],
                      "target_model": "no-such-model"},
        }
        with pytest.raises(ServiceError) as excinfo:
            service.create_task(ctx, payload)
        assert excinfo.value.code == "E_SCHEMA_INVALID"

    def test_empty_dialogue_rejected(self, service) -> None:
        ctx = service.authenticate("host-agent-alpha")
        payload = {
            "api_version": "1", "request_id": "r", "idempotency_key": "k3",
            "connector_id": "host-agent-alpha", "tenant_id": "t-001",
            "op": "generate.v1",
            "input": {"mode": "zero", "dialogue": [], "target_model": "deepseek"},
        }
        with pytest.raises(ServiceError) as excinfo:
            service.create_task(ctx, payload)
        assert excinfo.value.code == "E_SCHEMA_INVALID"


class TestMcp:
    def test_registry(self) -> None:
        tools = list_tools()
        assert len(tools) == 18
        assert len({tool["name"] for tool in tools}) == 18
        assert all(tool["description"] for tool in tools)

    def test_unknown_tool(self, service) -> None:
        ctx = service.authenticate("host-agent-alpha")
        with pytest.raises(ServiceError) as excinfo:
            call_tool("pg_nope", {}, service, ctx)
        assert excinfo.value.code == "E_UNSUPPORTED_OP"

    def test_capabilities_equivalence(self, service) -> None:
        from prompt5.connector.api import build_connector_app
        from fastapi.testclient import TestClient

        config = load_config(CONFIG).data
        app = build_connector_app(config)
        client = TestClient(app)
        http_body = client.get("/v1/capabilities",
                               headers={"Authorization": "Bearer host-agent-alpha"}).json()
        ctx = service.authenticate("host-agent-alpha")
        assert call_tool("pg_capabilities", {}, service, ctx) == http_body
