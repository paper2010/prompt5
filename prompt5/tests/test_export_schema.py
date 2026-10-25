"""M1 · Schema 导出测试：4 份产物 + Draft 2020-12 机器校验。"""

from __future__ import annotations

import json

from jsonschema import Draft202012Validator

from prompt5.export_schema import SCHEMAS, export, main


def test_exports_four_schemas(tmp_path) -> None:
    written = export(tmp_path)
    assert len(written) == 4
    names = sorted(path.name for path in written)
    assert names == [
        "eval_evidence.v1.schema.json",
        "ir.v3.schema.json",
        "patch.v3.schema.json",
        "task_request.v1.schema.json",
    ]


def test_schemas_are_valid_and_have_properties(tmp_path) -> None:
    for path in export(tmp_path):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema.get("properties"), path.name
        assert schema.get("$defs") or schema.get("type"), path.name


def test_schema_matches_model_fields(tmp_path) -> None:
    export(tmp_path)
    for name, model in SCHEMAS.items():
        schema = json.loads((tmp_path / f"{name}.schema.json").read_text(encoding="utf-8"))
        if name == "ir.v3":
            assert set(schema["properties"]) >= {
                "ir_id",
                "version",
                "checksum",
                "slots",
                "item_ids",
                "protect_registry",
            }
        if name == "patch.v3":
            assert {"patch_id", "base", "intent", "ops"} <= set(schema["properties"])
        if name == "eval_evidence.v1":
            assert {"reproduction_tier", "judge", "level"} <= set(schema["properties"])


def test_cli_main(tmp_path, capsys) -> None:
    code = main(["--out", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "exported 4 schemas" in out
