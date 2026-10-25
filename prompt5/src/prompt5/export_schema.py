"""导出四份 JSON Schema 并做机器校验（DoD：4 份 Schema + 自校验）。

`python -m prompt5.export_schema [--out specs]`
校验使用 jsonschema 的 Draft 2020-12 metaschema（`check_schema`），
与 check-jsonschema CLI 等价（后者只是其包装）。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .contracts import EvalEvidence, TaskRequest
from .ir import IR
from .patch import Patch

__all__ = ["SCHEMAS", "export", "main"]

SCHEMAS: dict[str, type] = {
    "ir.v3": IR,
    "patch.v3": Patch,
    "task_request.v1": TaskRequest,
    "eval_evidence.v1": EvalEvidence,
}


def export(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, model in SCHEMAS.items():
        schema = model.model_json_schema()
        Draft202012Validator.check_schema(schema)
        path = out_dir / f"{name}.schema.json"
        path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prompt5.export_schema")
    parser.add_argument("--out", default="specs")
    args = parser.parse_args(argv)

    written = export(Path(args.out))
    for path in written:
        size = path.stat().st_size
        print(f"OK {path} ({size} bytes, Draft2020-12 valid)")
    print(f"exported {len(written)} schemas to {args.out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
