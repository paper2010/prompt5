"""SSRF 守卫：回调 URL 校验（注册与投递共用）。"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

__all__ = ["SSRFError", "validate_callback_url"]

_BLOCKED_HOSTNAMES = {
    "localhost", "metadata.google.internal", "metadata", "instance-data",
}
_BLOCKED_PORTS = {22, 25, 3306, 5432, 6379, 9200, 11211}


class SSRFError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _resolve(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise SSRFError(f"DNS 解析失败：{host}") from exc
    return sorted({info[4][0] for info in infos})


def validate_callback_url(url: str, *, allowlist: list[str] | None = None) -> str:
    """校验回调 URL；通过则返回规范化 URL，失败抛 SSRFError。

    拒绝：非 http/https、内网/环回/链路本地/保留地址、云元数据域名、
    非常见管理端口（可选白名单域名放行）。
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SSRFError("仅允许 http/https")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise SSRFError("缺少主机名")
    if allowlist and host in {item.lower() for item in allowlist}:
        return url
    if host in _BLOCKED_HOSTNAMES:
        raise SSRFError(f"禁止的主机名：{host}")
    if parsed.port and parsed.port in _BLOCKED_PORTS:
        raise SSRFError(f"禁止的端口：{parsed.port}")

    for address in _resolve(host):
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise SSRFError(f"非法解析结果：{address}") from exc
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise SSRFError(f"禁止的地址段：{address}")
    return url
