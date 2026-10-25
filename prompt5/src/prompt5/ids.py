"""标识符：patch_id（ULID）、item_id 派生与校验。

规则来源：《搭建执行方案》§4.2
  - patch_id：服务器分配的 26 位 ULID（Crockford Base32），不可变；重放取存储结果，不重算
  - item_id：sha256(JCS([patch_id, op_index])) 前 10 位小写 hex；与既有 ID 冲突时每次追加 2 位
  - item_id 文法：[a-z0-9][a-z0-9-]{4,14}[a-z0-9]（6–16 位、首尾非连字符、永不复用）
"""

from __future__ import annotations

import os
import re
import time

from .canonical import CanonicalError, sha256_hex

__all__ = [
    "CROCKFORD",
    "new_patch_id",
    "new_ir_id",
    "derive_item_id",
    "is_valid_item_id",
    "ITEM_ID_RE",
]

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ITEM_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{4,14}[a-z0-9]$")
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")

_MAX_ITEM_ID_LEN = 16
_MIN_ITEM_ID_LEN = 6


def _encode_ulid_time(ms: int) -> str:
    if ms < 0 or ms >= 1 << 48:
        raise ValueError("timestamp out of ULID range")
    chars = []
    for _ in range(10):
        chars.append(CROCKFORD[ms & 0x1F])
        ms >>= 5
    return "".join(reversed(chars))


def _encode_ulid_random(raw: bytes) -> str:
    """80 bit 随机数 → 16 位 Crockford Base32。"""
    if len(raw) != 10:
        raise ValueError("ULID randomness must be 10 bytes")
    value = int.from_bytes(raw, "big")
    chars = []
    for _ in range(16):
        chars.append(CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def new_ir_id() -> str:
    """IR 标识（服务端生成，非寻址用途）。"""
    return "ir-" + new_patch_id().lower()[:20]


def new_patch_id(*, timestamp_ms: int | None = None) -> str:
    """生成 patch_id。timestamp_ms 仅测试注入用；生产路径使用当前时钟 + os.urandom。"""
    ms = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    ulid = _encode_ulid_time(ms) + _encode_ulid_random(os.urandom(10))
    assert _ULID_RE.match(ulid), "internal ULID encoding error"
    return ulid


def is_valid_item_id(candidate: str) -> bool:
    return bool(ITEM_ID_RE.match(candidate))


def derive_item_id(patch_id: str, op_index: int, existing: set[str] | None = None) -> str:
    """确定性派生 item_id；冲突时按 2 位步长扩展（同 base 同 patch 结果稳定）。"""
    if op_index < 0:
        raise ValueError("op_index must be >= 0")
    digest = sha256_hex([patch_id, op_index])
    width = 10
    existing = existing or set()
    while width <= len(digest):
        candidate = digest[:width]
        if candidate not in existing and is_valid_item_id(candidate):
            return candidate
        width += 2
    raise CanonicalError(
        f"item_id collision unresolved for patch={patch_id} op={op_index}"
    )
