"""M6 在线会话：语义门控 + 建议四元组 + epoch CAS + fencing + 事件联动。

契约（执行方案 §6.1/§6.7）：
- 语义分类在服务端完成：寒暄/进展不作废在途建议；材料/目标/约束/纠正→作废；不确定→保守作废；
- 建议携带四元组 {session_epoch, base_checksum, intent_hash, context_hash}，应用时逐项核对；
- 建议不可变（按 suggestion_id 取原 Patch），重复应用幂等返回首次结果；
- 应用成功 → session_epoch +1（其余在途建议自动失效）。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from ..canonical import sha256_hex
from ..ids import new_patch_id
from ..ir import IR
from ..patch import Patch
from .m6_events import emit

__all__ = ["SessionError", "TurnSignal", "classify_turn", "SessionStore"]

TurnKind = Literal["chitchat", "progress", "material", "goal", "constraint", "correction", "uncertain"]

_CORRECTION = ("不对", "不是这个", "错了", "我说的是", "纠正", "改回来")
_MATERIAL = ("上传", "附件", "文件", "截图", "链接", "材料", "csv", "excel", "pdf")
_GOAL = ("改成", "改为", "换一个", "目标是", "调整为", "重做")
_CONSTRAINT = ("必须", "不要", "禁止", "不能", "至少", "最多", "控制在", "限定")
_CHITCHAT = ("好的", "谢谢", "收到", "嗯", "ok", "OK", "继续", "明白", "辛苦了", "了", "好", "行", "哈")
_PROGRESS = ("进度", "已完成", "下一步", "正在", "第", "接着", "继续处理")

_INVALIDATING: set[str] = {"material", "goal", "constraint", "correction", "uncertain"}


@dataclass
class TurnSignal:
    kind: TurnKind
    invalidates: bool

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "invalidates": self.invalidates}


def _is_pure_chitchat(content: str) -> bool:
    """整条消息只由寒暄词构成才算 chitchat（避免「嗯这个再想想」被误判）。"""
    import re

    stripped = re.sub(r"[，。！？、,.!?~\s]", "", content)
    if not stripped or len(stripped) > 10:
        return False
    rest = stripped
    for token in sorted(_CHITCHAT, key=len, reverse=True):
        rest = rest.replace(token, "")
    return rest == ""


def classify_turn(text: str) -> TurnSignal:
    """规则分类；无法判定时按 uncertain 处理（保守作废）。"""
    content = (text or "").strip()
    if not content:
        return TurnSignal("uncertain", True)
    if any(word in content for word in _CORRECTION):
        return TurnSignal("correction", True)
    if any(word in content for word in _MATERIAL):
        return TurnSignal("material", True)
    if any(word in content for word in _GOAL):
        return TurnSignal("goal", True)
    if any(word in content for word in _CONSTRAINT):
        return TurnSignal("constraint", True)
    if any(word in content for word in _PROGRESS):
        return TurnSignal("progress", False)
    if _is_pure_chitchat(content):
        return TurnSignal("chitchat", False)
    return TurnSignal("uncertain", True)


class SessionError(Exception):
    def __init__(self, code: str, status: int, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}".strip())
        self.code = code
        self.status = status
        self.detail = detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SessionStore:
    def __init__(self, conn: sqlite3.Connection, *, idle_hours: int = 24) -> None:
        self.conn = conn
        self.idle_hours = idle_hours

    # ---------------------------------------------------------------- session
    def open(self, ir_id: str) -> dict[str, Any]:
        session_id = f"s-{new_patch_id().lower()[:16]}"
        deadline = (_now() + timedelta(hours=self.idle_hours)).isoformat(timespec="seconds")
        self.conn.execute(
            "INSERT INTO sessions(session_id, ir_id, epoch, last_turn_seq, idle_deadline, state)"
            " VALUES(?,?,0,0,?,'open')",
            (session_id, ir_id, deadline),
        )
        emit(self.conn, session_id, "session.opened", {"ir_id": ir_id})
        return self.get(session_id)

    def get(self, session_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            raise SessionError("E_FIELD_UNKNOWN", 404, f"session {session_id} not found")
        return dict(row)

    def close(self, session_id: str) -> dict[str, Any]:
        self.get(session_id)
        self.conn.execute("UPDATE sessions SET state='closed' WHERE session_id=?", (session_id,))
        emit(self.conn, session_id, "session.closed")
        return self.get(session_id)

    def expire_idle(self, *, now: datetime | None = None) -> int:
        moment = (now or _now()).isoformat(timespec="seconds")
        rows = self.conn.execute(
            "SELECT session_id FROM sessions WHERE state='open' AND idle_deadline < ?", (moment,)
        ).fetchall()
        for row in rows:
            self.conn.execute("UPDATE sessions SET state='closed' WHERE session_id=?", (row["session_id"],))
            emit(self.conn, row["session_id"], "session.closed", {"reason": "idle"})
        return len(rows)

    # ---------------------------------------------------------------- turns
    def record_turn(
        self, session_id: str, text: str, *, role: str = "user", seq: int | None = None
    ) -> dict[str, Any]:
        session = self.get(session_id)
        if session["state"] != "open":
            raise SessionError("E_FENCING_STALE", 409, "session closed")

        expected = int(session["last_turn_seq"]) + 1
        if seq is not None and seq != expected:
            raise SessionError("E_EVENT_ORDER", 422, f"expected seq {expected}, got {seq}")

        signal = classify_turn(text)
        text_hash = sha256_hex({"text": text})
        self.conn.execute(
            "INSERT INTO turns(session_id, seq, role, text, text_hash, kind, invalidates, created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (session_id, expected, role, text, text_hash, signal.kind, int(signal.invalidates),
             _now().isoformat(timespec="seconds")),
        )
        deadline = (_now() + timedelta(hours=self.idle_hours)).isoformat(timespec="seconds")
        self.conn.execute(
            "UPDATE sessions SET last_turn_seq=?, idle_deadline=? WHERE session_id=?",
            (expected, deadline, session_id),
        )

        invalidated = 0
        if signal.invalidates:
            cursor = self.conn.execute(
                "UPDATE suggestions SET state='invalidated' WHERE session_id=? AND state='proposed'",
                (session_id,),
            )
            invalidated = cursor.rowcount or 0

        emit(
            self.conn,
            session_id,
            "turn.recorded",
            {"seq": expected, "kind": signal.kind, "invalidates": signal.invalidates,
             "invalidated_suggestions": invalidated},
        )
        return {"seq": expected, **signal.to_dict(), "invalidated_suggestions": invalidated}

    def turns(self, session_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute(
            "SELECT * FROM turns WHERE session_id=? ORDER BY seq", (session_id,)
        )]

    # ---------------------------------------------------------------- hashes
    def context_hash(self, session_id: str, *, window: int = 3) -> str:
        """只由「语义类轮」参与（invalidates=1）：寒暄/进展不改变上下文哈希，
        避免每条寒暄都让在途建议失效（补丁饥饿）。"""
        rows = self.conn.execute(
            "SELECT text_hash FROM turns WHERE session_id=? AND invalidates=1"
            " ORDER BY seq DESC LIMIT ?",
            (session_id, window),
        ).fetchall()
        return sha256_hex([row["text_hash"] for row in rows])

    @staticmethod
    def intent_hash(ir: IR) -> str:
        return sha256_hex(
            {
                "goal": ir.slots.goal.model_dump(mode="json"),
                "constraints": ir.slots.constraints.model_dump(mode="json"),
            }
        )

    # ---------------------------------------------------------------- suggestion
    def propose(self, session_id: str, patch: Patch, ledger) -> dict[str, Any]:
        session = self.get(session_id)
        if session["state"] != "open":
            raise SessionError("E_FENCING_STALE", 409, "session closed")
        ir = ledger.current(session["ir_id"])
        if patch.base.checksum != ir.checksum:
            raise SessionError("E_STALE_OVERLAY", 409, "suggestion base is not current IR")

        suggestion_id = f"sg-{new_patch_id().lower()[:16]}"
        record = {
            "suggestion_id": suggestion_id,
            "session_id": session_id,
            "patch_json": json.dumps(patch.model_dump(mode="json", by_alias=True), ensure_ascii=False),
            "patch_hash": patch.patch_hash,
            "epoch": int(session["epoch"]),
            "base_checksum": ir.checksum,
            "intent_hash": self.intent_hash(ir),
            "context_hash": self.context_hash(session_id),
        }
        self.conn.execute(
            "INSERT INTO suggestions(suggestion_id, session_id, patch_json, patch_hash, epoch,"
            " base_checksum, intent_hash, context_hash, state, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,'proposed',?)",
            (
                record["suggestion_id"], session_id, record["patch_json"], record["patch_hash"],
                record["epoch"], record["base_checksum"], record["intent_hash"],
                record["context_hash"], _now().isoformat(timespec="seconds"),
            ),
        )
        emit(self.conn, session_id, "suggestion.proposed", {
            "suggestion_id": suggestion_id,
            "patch_hash": patch.patch_hash,
            "epoch": record["epoch"],
            "base_checksum": record["base_checksum"],
            "intent_hash": record["intent_hash"],
            "context_hash": record["context_hash"],
        })
        return record

    def get_suggestion(self, suggestion_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM suggestions WHERE suggestion_id=?", (suggestion_id,)
        ).fetchone()
        if row is None:
            raise SessionError("E_FIELD_UNKNOWN", 404, f"suggestion {suggestion_id} not found")
        return dict(row)

    def apply(
        self,
        session_id: str,
        suggestion_id: str,
        *,
        epoch: int,
        base_checksum: str,
        intent_hash: str,
        context_hash: str,
        ledger,
        fencing_token: int | None = None,
    ) -> dict[str, Any]:
        session = self.get(session_id)
        suggestion = self.get_suggestion(suggestion_id)

        if suggestion["session_id"] != session_id:
            raise SessionError("E_SCOPE", 403, "suggestion belongs to another session")
        if suggestion["state"] == "applied":
            return {"status": "idempotent", "suggestion_id": suggestion_id,
                    "ir_version": ledger.current(session["ir_id"]).version}
        if suggestion["state"] == "invalidated":
            raise SessionError("E_SUGGESTION_STALE", 409, "suggestion invalidated by later turns")
        if session["state"] != "open":
            raise SessionError("E_FENCING_STALE", 409, "session closed")

        current_epoch = int(session["epoch"])
        if epoch != current_epoch or int(suggestion["epoch"]) != current_epoch:
            raise SessionError("E_FENCING_STALE", 409,
                               f"epoch mismatch: session={current_epoch} provided={epoch}")
        if fencing_token is not None and fencing_token != current_epoch:
            raise SessionError("E_FENCING_STALE", 409, "fencing token is stale")

        ir = ledger.current(session["ir_id"])
        if base_checksum != suggestion["base_checksum"] or base_checksum != ir.checksum:
            raise SessionError("E_BASE_DRIFT", 409, "base checksum mismatch")
        if intent_hash != suggestion["intent_hash"] or self.intent_hash(ir) != suggestion["intent_hash"]:
            raise SessionError("E_FENCING_STALE", 409, "intent changed since suggestion")
        if context_hash != suggestion["context_hash"] or self.context_hash(session_id) != suggestion["context_hash"]:
            raise SessionError("E_FENCING_STALE", 409, "context changed since suggestion")

        patch = Patch.model_validate(json.loads(suggestion["patch_json"]))
        result = ledger.apply(patch)

        self.conn.execute(
            "UPDATE suggestions SET state='applied', applied_at=? WHERE suggestion_id=?",
            (_now().isoformat(timespec="seconds"), suggestion_id),
        )
        self.conn.execute(
            "UPDATE sessions SET epoch=epoch+1 WHERE session_id=?", (session_id,)
        )
        emit(self.conn, session_id, "suggestion.applied", {
            "suggestion_id": suggestion_id,
            "ir_version": result.ir.version,
            "new_epoch": current_epoch + 1,
        })
        return {"status": "applied", "suggestion_id": suggestion_id,
                "ir_version": result.ir.version, "new_epoch": current_epoch + 1}
