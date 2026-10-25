"""连接器：HTTP 与 MCP 共用服务层。"""

from .api import Context, ConnectorService, ServiceError, build_connector_app

__all__ = ["Context", "ConnectorService", "ServiceError", "build_connector_app"]
