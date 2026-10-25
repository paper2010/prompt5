"""事件 outbox：持久化 + 有界重试 + 死信 + 游标拉取（在线模式用）。

契约（执行方案 §6.6/§6.8）：
- 事件先落库（state=pending），投递失败按退避重试，超过上限进 DLQ（state=dead）；
- 客户端可用 `pull(after_seq)` 自愈，推送与拉取构成 at-least-once；
- event_seq 在会话内单调递增，乱序由数据库主键保证不会重复。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from ..ids import new_patch_id

__all__ = ["OutboxEvent", "emit", "pull", "deliver_pending", "event_to_dict"]

_MAX_ATTEMPTS = 5


@dataclass
class OutboxEvent:
    event_id: str
    session_id: str
    event_seq: int
    type: str
    payload: dict[str, Any]
    state: str
    attempts: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def emit(conn: sqlite3.Connection, session_id: str, type_: str,
         payload: dict[str, Any] | None = None) -> OutboxEvent:
    row = conn.execute(
        "SELECT COALESCE(MAX(event_seq), 0) AS seq FROM events WHERE session_id=?", (session_id,)
    ).fetchone()
    seq = int(row["seq"]) + 1
    event_id = f"ev-{new_patch_id().lower()[:16]}"
    conn.execute(
        "INSERT INTO events(event_id, session_id, event_seq, type, payload_json, state, attempts, next_attempt_at)"
        " VALUES(?,?,?,?,?,?,0,?)",
        (event_id, session_id, seq, type_, json.dumps(payload or {}, ensure_ascii=False), "pending", _now()),
    )
    return OutboxEvent(event_id, session_id, seq, type_, payload or {}, "pending", 0)


def pull(conn: sqlite3.Connection, session_id: str, after_seq: int = 0,
         limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM events WHERE session_id=? AND event_seq>? ORDER BY event_seq LIMIT ?",
        (session_id, after_seq, limit),
    ).fetchall()
    return [
        {
            "event_id": row["event_id"],
            "event_seq": row["event_seq"],
            "type": row["type"],
            "payload": json.loads(row["payload_json"]),
            "state": row["state"],
            "attempts": row["attempts"],
        }
        for row in rows
    ]


def event_to_dict(event: OutboxEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "session_id": event.session_id,
        "event_seq": event.event_seq,
        "type": event.type,
        "payload": event.payload,
    }


def deliver_pending(
    conn: sqlite3.Connection,
    deliver: Callable[[dict[str, Any]], None],
    *,
    max_attempts: int = _MAX_ATTEMPTS,
) -> dict[str, int]:
    """投递 pending 事件；失败重试到上限后进 DLQ（state=dead）。"""
    stats = {"delivered": 0, "retried": 0, "dead": 0}
    rows = conn.execute(
        "SELECT * FROM events WHERE state='pending' ORDER BY event_seq"
    ).fetchall()
    for row in rows:
        payload = {
            "event_id": row["event_id"],
            "event_seq": row["event_seq"],
            "type": row["type"],
            "session_id": row["session_id"],
            "payload": json.loads(row["payload_json"]),
        }
        try:
            deliver(payload)
        except Exception:  # noqa: BLE001 - 投递失败一律走重试/DLQ
            attempts = int(row["attempts"]) + 1
            if attempts >= max_attempts:
                conn.execute(
                    "UPDATE events SET state='dead', attempts=? WHERE event_id=?",
                    (attempts, row["event_id"]),
                )
                stats["dead"] += 1
            else:
                conn.execute(
                    "UPDATE events SET attempts=?, state='pending', next_attempt_at=? WHERE event_id=?",
                    (attempts, _now(), row["event_id"]),
                )
                stats["retried"] += 1
        else:
            conn.execute(
                "UPDATE events SET state='delivered', attempts=attempts+1 WHERE event_id=?",
                (row["event_id"],),
            )
            stats["delivered"] += 1
    return stats
