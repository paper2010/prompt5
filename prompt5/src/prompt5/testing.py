"""测试工厂（非生产代码）：构造 IR / Patch / Op 的确定性样例。"""

from __future__ import annotations

from typing import Any, Iterable

from .ir import IR, build_ir
from .patch import Op, Patch

__all__ = [
    "make_ir",
    "make_patch",
    "add_op",
    "delete_op",
    "rewrite_op",
    "move_op",
    "ids_of",
]

_FIXED_PATCH_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
_FIXED_CREATED = {"by": "test", "at": "2026-01-01T00:00:00Z", "strategy_id": "s1", "operator": "ci"}


def make_ir(
    *,
    ir_id: str = "ir-1",
    lineage_id: str = "lin-1",
    role: str = "",
    must: Iterable[str] | None = None,
    must_not: Iterable[str] | None = None,
    style: Iterable[str] | None = None,
    workflow: Iterable[str] | None = None,
    done_criteria: Iterable[str] | None = None,
    freeform: Iterable[str] | None = None,
) -> IR:
    payload: dict[str, Any] = {
        "ir_id": ir_id,
        "lineage_id": lineage_id,
        "created": dict(_FIXED_CREATED),
        "slots": {
            "role": role,
            "goal": {
                "outcome": "produce the deliverable",
                "done_criteria": list(done_criteria or ["checklist passes"]),
                "non_goals": [],
            },
            "inputs": [],
            "output": {"format": "text"},
            "constraints": {
                "must": list(must if must is not None else ["must-alpha", "must-beta", "must-gamma"]),
                "must_not": list(must_not or []),
                "style": list(style or []),
            },
            "examples": [],
            "workflow": list(workflow if workflow is not None else ["step-one", "step-two"]),
            "feedback_protocol": {},
        },
        "freeform_extras": [{"text": text} for text in (freeform if freeform is not None else ["note", "note-two"])],
        "provenance_map": {},
        "protect_registry": [],
    }
    return build_ir(payload)


def ids_of(ir: IR, path: str) -> list[str]:
    return list(ir.item_ids[path])


def add_op(loc: str, content: Any, reason: str = "add") -> dict[str, Any]:
    return {"op": "ADD", "loc": loc, "content": content, "reason": reason}


def delete_op(loc: str, evidence: Iterable[str] = ("run:1",), reason: str = "delete") -> dict[str, Any]:
    return {"op": "DELETE", "loc": loc, "reason": reason, "evidence_refs": list(evidence)}


def rewrite_op(loc: str, content: Any, reason: str = "rewrite") -> dict[str, Any]:
    return {"op": "REWRITE", "loc": loc, "content": content, "reason": reason}


def move_op(loc: str, to: dict[str, Any]) -> dict[str, Any]:
    return {"op": "MOVE", "loc": loc, "to": to, "reason": "reorder"}


def make_patch(
    base: IR,
    ops: Iterable[dict[str, Any] | Op],
    *,
    intent: str = "improve",
    patch_id: str = _FIXED_PATCH_ID,
    idempotency_key: str = "idem-1",
    model_scope: str | None = None,
) -> Patch:
    body = {
        "schema_version": "3",
        "patch_id": patch_id,
        "base": {"ir_id": base.ir_id, "version": base.version, "checksum": base.checksum},
        "model_scope": model_scope,
        "intent": intent,
        "ops": [op if isinstance(op, dict) else op.model_dump() for op in ops],
        "idempotency_key": idempotency_key,
        "created": dict(_FIXED_CREATED),
    }
    patch = Patch.model_validate(body)
    return patch.model_copy(update={"patch_hash": patch.compute_hash()})
