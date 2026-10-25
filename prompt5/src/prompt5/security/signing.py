"""回调签名：HMAC-SHA256 over RFC 8785 canonical JSON（排除 signature 字段）。"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

from ..canonical import dumps

__all__ = ["SigningError", "sign_event", "verify_event"]


class SigningError(ValueError):
    pass


def _material(event: dict[str, Any], key_id: str, timestamp: int) -> bytes:
    body = {key: value for key, value in event.items()
            if key not in {"signature", "key_id", "timestamp"}}
    return dumps({"body": body, "key_id": key_id, "timestamp": timestamp}).encode("utf-8")


def sign_event(event: dict[str, Any], secret: str, *, key_id: str = "k1",
               timestamp: int | None = None) -> dict[str, Any]:
    moment = int(time.time() if timestamp is None else timestamp)
    signature = hmac.new(secret.encode("utf-8"), _material(event, key_id, moment),
                         hashlib.sha256).hexdigest()
    return {**event, "key_id": key_id, "timestamp": moment, "signature": signature}


def verify_event(event: dict[str, Any], secret: str, *, tolerance: int = 300,
                 now: int | None = None) -> bool:
    signature = event.get("signature")
    key_id = event.get("key_id")
    timestamp = event.get("timestamp")
    if not signature or not key_id or not isinstance(timestamp, int):
        raise SigningError("缺少签名字段")
    current = int(time.time() if now is None else now)
    if abs(current - timestamp) > tolerance:
        raise SigningError("时间戳超出容差")
    expected = hmac.new(secret.encode("utf-8"), _material(event, key_id, timestamp),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise SigningError("签名不匹配")
    return True
