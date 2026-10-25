"""本地单用户 UI 启动入口：FastAPI + 可选的 web/dist 静态托管。"""

from __future__ import annotations

import argparse
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse, JSONResponse

from .config import load_config
from .connector.api import build_connector_app

__all__ = ["create_ui_app", "main"]


def create_ui_app(config_path: Path, *, db_path: Path, save_path: Path):
    root = Path(__file__).resolve().parents[2]
    app = build_connector_app(
        load_config(config_path).data,
        db_path=str(db_path),
        project_root=root,
        config_path=save_path,
    )
    dist = root / "web" / "dist"

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path == "healthz" or path.startswith("v1/"):
            raise HTTPException(status_code=404)
        if not dist.exists():
            return JSONResponse(
                {"error_code": "E_UI_NOT_BUILT", "detail": "Run npm run build in web/ first."},
                status_code=503,
            )
        candidate = (dist / path).resolve()
        try:
            candidate.relative_to(dist.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=404) from exc
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")

    return app


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(prog="python -m prompt5.ui")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--config", default=None)
    parser.add_argument("--db", default=str(root / "prompt5.db"))
    args = parser.parse_args(argv)

    default_config = root / "config.yaml"
    example_config = root / "config.example.yaml"
    loaded_path = Path(args.config) if args.config else (default_config if default_config.exists() else example_config)
    save_path = default_config if loaded_path.resolve() == example_config.resolve() else loaded_path
    app = create_ui_app(loaded_path, db_path=Path(args.db), save_path=save_path)

    import uvicorn
    print(f"Prompt5 UI: http://{args.host}:{args.port}")
    print(f"Config: {loaded_path} | DB: {args.db}")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
