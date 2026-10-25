"""评测缓存：键必须覆盖「模型/裁判/环境/基准/重复」全部分量，任一变即未命中。

契约（执行方案 §6.1）：评测缓存禁跨环境/跨模型/跨裁判复用；本模块只是内存实现，
键构造规则与生产一致，M6 接入持久化时直接复用 `EvalCache.key`。
"""

from __future__ import annotations

from typing import Any

from ...canonical import sha256_hex, tuple_hash

__all__ = ["EvalCache"]


class EvalCache:
    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(**components: Any) -> str:
        """所有分量按 (字段名, 值) 参与哈希；dict/list 先规范化。"""
        pairs: list[tuple[str, str]] = []
        for name in sorted(components):
            value = components[name]
            if isinstance(value, str):
                rendered = value
            elif value is None:
                rendered = "none"
            else:
                rendered = sha256_hex(value)
            pairs.append((name, rendered))
        return tuple_hash(pairs)

    def get(self, key: str) -> Any | None:
        if key in self._store:
            self.hits += 1
            return self._store[key]
        self.misses += 1
        return None

    def put(self, key: str, value: Any) -> None:
        self._store[key] = value

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "size": len(self._store)}
