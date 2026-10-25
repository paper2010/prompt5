"""RFC 8785 (JSON Canonicalization Scheme, JCS) + SHA-256 checksums.

唯一序列化标准：IR checksum、Patch hash、事件签名、tuple_hash 全部共用本模块。
与 RFC 8785 §3.2 对齐：
  - 对象键按 UTF-16 code unit 排序（非 code point）
  - 无空白；键必须为字符串
  - 控制字符：\\b \\t \\n \\f \\r 短转义，其余 C0 用 \\u00xx（小写 hex）
  - 非 ASCII 原样输出（UTF-8），不转义 '/'，不做 \\uXXXX 扩展转义
  - 数字按 ECMAScript Number::toString（最短往返表示）；-0 → "0"；NaN/Infinity 拒绝
  - 孤立代理项拒绝
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Iterable, Sequence

__all__ = [
    "CanonicalError",
    "dumps",
    "sha256_hex",
    "tuple_hash",
    "number_to_string",
]


class CanonicalError(ValueError):
    """输入无法按 RFC 8785 规范化（类型不支持 / 数字非法 / 孤立代理项 / 非字符串键）。"""


_ES_SPLIT = re.compile(r"[eE]")


def _utf16_key(s: str) -> bytes:
    """UTF-16BE 字节序 == UTF-16 code unit 序（RFC 8785 §3.2.3）。"""
    try:
        return s.encode("utf-16-be")
    except UnicodeEncodeError as exc:  # 孤立代理项
        raise CanonicalError("lone surrogate in object key") from exc


def _escape_string(s: str) -> str:
    out: list[str] = ['"']
    for ch in s:
        code = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif code == 0x08:
            out.append("\\b")
        elif code == 0x09:
            out.append("\\t")
        elif code == 0x0A:
            out.append("\\n")
        elif code == 0x0C:
            out.append("\\f")
        elif code == 0x0D:
            out.append("\\r")
        elif code < 0x20:
            out.append("\\u%04x" % code)
        elif 0xD800 <= code <= 0xDFFF:
            raise CanonicalError("lone surrogate in string")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def number_to_string(value: int | float) -> str:
    """ECMAScript Number::toString 等价实现（RFC 8785 §3.2.2.3）。

    依赖 Python 的 repr() 提供「最短往返数字串」，再按 ES 规则重排小数点/指数。
    """
    if isinstance(value, int) and not isinstance(value, bool):
        if abs(value) < 10**21:
            return str(value)
        value = float(value)

    x = float(value)
    if not math.isfinite(x):
        raise CanonicalError("NaN and Infinity are not valid JSON numbers")
    if x == 0:
        return "0"  # 含 -0.0

    negative = x < 0
    r = repr(abs(x))
    if "e" in r or "E" in r:
        mantissa, exp_part = _ES_SPLIT.split(r)
        exp10 = int(exp_part)
    else:
        mantissa, exp10 = r, 0

    if "." in mantissa:
        int_part, frac_part = mantissa.split(".")
    else:
        int_part, frac_part = mantissa, ""

    digits = (int_part + frac_part).lstrip("0") or "0"
    exp10 -= len(frac_part)
    while len(digits) > 1 and digits.endswith("0"):
        digits = digits[:-1]
        exp10 += 1

    k = len(digits)          # 有效数字位数
    n = k + exp10            # 小数点位置：value = 0.digits × 10^n

    if 0 < n <= 21:
        if k <= n:
            body = digits + "0" * (n - k)
        else:
            body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + digits
    else:
        body = digits[0] + ("." + digits[1:] if k > 1 else "")
        body += "e" + ("+" if n - 1 >= 0 else "-") + str(abs(n - 1))

    return ("-" if negative else "") + body


def dumps(obj: Any) -> str:
    """规范化序列化为 str（UTF-8 输出前再 encode）。"""
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        return number_to_string(obj)
    if isinstance(obj, str):
        return _escape_string(obj)
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(dumps(item) for item in obj) + "]"
    if isinstance(obj, dict):
        for key in obj:
            if not isinstance(key, str):
                raise CanonicalError("object keys must be strings")
        items = sorted(obj.items(), key=lambda kv: _utf16_key(kv[0]))
        return "{" + ",".join(_escape_string(k) + ":" + dumps(v) for k, v in items) + "}"
    raise CanonicalError(f"unsupported type: {type(obj).__name__}")


def dumps_bytes(obj: Any) -> bytes:
    return dumps(obj).encode("utf-8")


def sha256_hex(obj: Any) -> str:
    """checksum / patch_hash / 签名基底统一入口：sha256(JCS(obj))，小写 hex。"""
    return hashlib.sha256(dumps_bytes(obj)).hexdigest()


def tuple_hash(pairs: Iterable[Sequence[str]]) -> str:
    """带字段名前缀的元组哈希（禁止裸字符串拼接，执行方案 D-13）。

    tuple_hash([("task","t-001"),("model","glm-5")]) == sha256(JCS([["task","t-001"],["model","glm-5"]]))
    """
    material: list[list[str]] = []
    for pair in pairs:
        seq = list(pair)
        if len(seq) != 2:
            raise CanonicalError("tuple_hash expects (key, value) pairs")
        material.append([str(seq[0]), str(seq[1])])
    return sha256_hex(material)
