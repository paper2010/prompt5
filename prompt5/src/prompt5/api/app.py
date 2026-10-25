"""API 入口（M0）：capabilities 冒烟。

FastAPI 可用时构建真实应用（M1 起扩展全部资源）；当前环境无 FastAPI，
按 NOTES.md #1 用 stdlib http.server 提供同一 payload 的冒烟服务。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:  # 可选依赖：缺失时 API 走 stdlib 兜底（见 NOTES #1）
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, Response
except ImportError:  # pragma: no cover
    FastAPI = None  # type: ignore[assignment]
    Request = None  # type: ignore[assignment]
    JSONResponse = None  # type: ignore[assignment]
    Response = None  # type: ignore[assignment]

from ..blobs import BlobError, BlobStore
from ..capabilities import CAPABILITIES, ERROR_CODES, MCP_TOOLS
from ..store.migrate import init_db

__all__ = ["capabilities_payload", "build_fastapi_app", "make_stdlib_server", "main"]

_IMPLEMENTED = {"discovery.v1"}  # 随里程碑推进（M1: score/render, M2: generate ...）


def capabilities_payload() -> dict[str, Any]:
    return {
        "api_version": "1",
        "service": "prompt5",
        "milestone": "M0",
        "capabilities": [
            {
                "op": op,
                "version": "1",
                "status": "stable" if op in _IMPLEMENTED else "planned",
                "ready": meta["ready"],
                "sync": meta["sync"],
                "scopes_required": meta["scope"],
            }
            for op, meta in CAPABILITIES.items()
        ],
        "mcp_tool_count": len(MCP_TOOLS),
        "error_code_count": len(ERROR_CODES),
    }


def build_fastapi_app(
    *, db_path: str | None = None, blob_root: str | None = None, max_blob_bytes: int | None = None
):  # pragma: no cover - 依赖缺失时不可达
    """真实 API 应用。缺 FastAPI 时抛 ImportError，由调用方降级。"""
    if FastAPI is None:  # pragma: no cover
        raise ImportError("fastapi not installed")

    app = FastAPI(title="prompt5", version="0.0.1")
    db = db_path or os.environ.get("PROMPT5_DB", "prompt5.db")
    conn = init_db(db, check_same_thread=False)
    kwargs = {"max_bytes": max_blob_bytes} if max_blob_bytes else {}
    store = BlobStore(conn, blob_root or os.environ.get("PROMPT5_BLOBS", "data/blobs"), **kwargs)
    app.state.blobs = store

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/capabilities")
    def capabilities() -> dict[str, Any]:
        return capabilities_payload()

    @app.post("/v1/blobs")
    async def upload_blob(request: Request):
        tenant = request.headers.get("x-tenant-id", "")
        mime = request.headers.get("x-blob-mime", "application/octet-stream")
        body = await request.body()
        try:
            meta = store.put(tenant, body, mime)
        except BlobError as exc:
            return JSONResponse(
                {"error_code": exc.code, "detail": exc.detail}, status_code=exc.status
            )
        return {
            "blob_id": meta.blob_id,
            "content_hash": meta.sha256,
            "size": meta.size,
            "mime": meta.mime,
            "expires_at": meta.expires_at,
        }

    @app.get("/v1/blobs/{blob_id}")
    def download_blob(blob_id: str, request: Request):
        tenant = request.headers.get("x-tenant-id", "")
        try:
            meta, content = store.get(tenant, blob_id)
        except BlobError as exc:
            return JSONResponse(
                {"error_code": exc.code, "detail": exc.detail}, status_code=exc.status
            )
        return Response(content=content, media_type=meta.mime)

    return app


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0] == "/v1/capabilities":
            body = json.dumps(capabilities_payload(), ensure_ascii=False).encode("utf-8")
            status = 200
        elif self.path.split("?")[0] == "/healthz":
            body = b'{"status":"ok"}'
            status = 200
        else:
            body = b'{"error_code":"E_UNSUPPORTED_OP","message":"not found"}'
            status = 501
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:  # 静默
        return


def make_stdlib_server(host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    """返回已绑定端口的服务器（port=0 → 随机端口，读 server_address[1]）。"""
    return ThreadingHTTPServer((host, port), _Handler)


def _serve(host: str, port: int) -> int:
    try:
        import uvicorn

        uvicorn.run(build_fastapi_app(), host=host, port=port, log_level="warning")
        return 0
    except ImportError:
        server = make_stdlib_server(host, port)
        actual = server.server_address[1]
        print(f"prompt5 api (stdlib fallback, FastAPI missing) listening on "
              f"http://{host}:{actual}/v1/capabilities", file=sys.stderr)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prompt5.api")
    parser.add_argument("--dry", action="store_true", help="打印 capabilities 并退出")
    parser.add_argument("--serve", action="store_true", help="启动 HTTP 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    if args.serve:
        return _serve(args.host, args.port)

    print(json.dumps(capabilities_payload(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
