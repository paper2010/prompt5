"""本地单用户 UI 启动入口：FastAPI + 可选的 web/dist 静态托管。"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse, JSONResponse

from .config import load_config
from .connector.api import build_connector_app

__all__ = ["create_ui_app", "main"]


def _bundle_root() -> Path:
    """Return the directory containing bundled assets (PyInstaller-aware)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[2]


def _default_data_dir(bundle_root: Path) -> Path:
    """Writable data directory for a zero-config desktop launch."""
    override = os.environ.get("PROMPT5_DATA_DIR")
    if override:
        return Path(override)
    if not getattr(sys, "frozen", False):
        return bundle_root
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "Prompt5"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Prompt5"
    return Path.home() / ".local" / "share" / "prompt5"


def _ensure_runtime_config(bundle_root: Path, data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    config_path = data_dir / "config.yaml"
    if not config_path.exists():
        example = bundle_root / "config.example.yaml"
        if not example.exists():
            raise FileNotFoundError(f"bundled config.example.yaml not found: {example}")
        shutil.copy2(example, config_path)
    return config_path


def create_ui_app(
    config_path: Path,
    *,
    db_path: Path,
    save_path: Path,
    bundle_root: Path | None = None,
):
    root = bundle_root or _bundle_root()
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
    bundle_root = _bundle_root()
    parser = argparse.ArgumentParser(prog="python -m prompt5.ui")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--config", default=None)
    parser.add_argument("--db", default=None)
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else _default_data_dir(bundle_root)
    example_config = bundle_root / "config.example.yaml"
    if args.config:
        loaded_path = Path(args.config)
    else:
        loaded_path = _ensure_runtime_config(bundle_root, data_dir)
    save_path = data_dir / "config.yaml" if loaded_path.resolve() == example_config.resolve() else loaded_path
    db_path = Path(args.db) if args.db else data_dir / "prompt5.db"
    app = create_ui_app(loaded_path, db_path=db_path, save_path=save_path, bundle_root=bundle_root)

    import uvicorn
    print(f"Prompt5 UI: http://{args.host}:{args.port}")
    print(f"Config: {loaded_path} | DB: {db_path}")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
