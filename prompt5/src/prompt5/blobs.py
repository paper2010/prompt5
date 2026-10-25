"""材料接入（blob）：服务端计算 SHA-256、MIME 白名单、大小/配额限制、TTL、租户隔离。

契约（执行方案 §7）：唯一入口是 blob 上传；**禁止服务端抓取任意外部 URL**。
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

__all__ = ["BlobError", "BlobMeta", "BlobStore", "ALLOWED_MIME"]

ALLOWED_MIME = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
    "image/png",
    "image/jpeg",
    "application/pdf",
}

MAX_BYTES_DEFAULT = 10 * 1024 * 1024
QUOTA_BYTES_DEFAULT = 1024 * 1024 * 1024  # 1 GiB / 租户
TTL_DAYS_DEFAULT = 30


class BlobError(Exception):
    def __init__(self, code: str, status: int, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}".strip())
        self.code = code
        self.status = status
        self.detail = detail


@dataclass
class BlobMeta:
    blob_id: str
    tenant_id: str
    sha256: str
    mime: str
    size: int
    created_at: str
    expires_at: str
    path: str


class BlobStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        root: str | Path,
        *,
        max_bytes: int = MAX_BYTES_DEFAULT,
        quota_bytes: int = QUOTA_BYTES_DEFAULT,
        ttl_days: int = TTL_DAYS_DEFAULT,
        allowed_mime: set[str] | None = None,
    ) -> None:
        self.conn = conn
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.quota_bytes = quota_bytes
        self.ttl_days = ttl_days
        self.allowed_mime = allowed_mime or set(ALLOWED_MIME)

    # ---------------------------------------------------------------- write
    def put(self, tenant_id: str, content: bytes, mime: str) -> BlobMeta:
        if not tenant_id:
            raise BlobError("E_AUTH_IDENTITY_MISMATCH", 401, "tenant required")
        if mime not in self.allowed_mime:
            raise BlobError("E_BLOB_MIME", 415, f"mime {mime!r} not allowed")
        if len(content) > self.max_bytes:
            raise BlobError("E_BLOB_TOO_LARGE", 413, f"{len(content)} > {self.max_bytes}")

        used = self.conn.execute(
            "SELECT COALESCE(SUM(size),0) AS total FROM blobs WHERE tenant_id=?", (tenant_id,)
        ).fetchone()["total"]
        if used + len(content) > self.quota_bytes:
            raise BlobError("E_BLOB_QUOTA", 429, "tenant quota exceeded")

        digest = hashlib.sha256(content).hexdigest()
        blob_id = f"bl-{digest[:16]}"
        existing = self.conn.execute(
            "SELECT * FROM blobs WHERE blob_id=? AND tenant_id=?", (blob_id, tenant_id)
        ).fetchone()
        if existing:
            return self._row_to_meta(existing)

        path = self.root / blob_id
        path.write_bytes(content)
        now = datetime.now(timezone.utc)
        meta = BlobMeta(
            blob_id=blob_id,
            tenant_id=tenant_id,
            sha256=digest,
            mime=mime,
            size=len(content),
            created_at=now.isoformat(timespec="seconds"),
            expires_at=(now + timedelta(days=self.ttl_days)).isoformat(timespec="seconds"),
            path=str(path),
        )
        self.conn.execute(
            "INSERT INTO blobs(blob_id, tenant_id, sha256, mime, size, path, created_at, expires_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (meta.blob_id, meta.tenant_id, meta.sha256, meta.mime, meta.size, meta.path,
             meta.created_at, meta.expires_at),
        )
        return meta

    # ---------------------------------------------------------------- read
    def get(self, tenant_id: str, blob_id: str) -> tuple[BlobMeta, bytes]:
        row = self.conn.execute("SELECT * FROM blobs WHERE blob_id=?", (blob_id,)).fetchone()
        if row is None:
            raise BlobError("E_FIELD_UNKNOWN", 404, f"blob {blob_id} not found")
        if row["tenant_id"] != tenant_id:
            raise BlobError("E_SCOPE", 403, "cross-tenant access denied")
        meta = self._row_to_meta(row)
        path = Path(meta.path)
        if not path.exists():
            raise BlobError("E_FIELD_UNKNOWN", 410, "blob content missing")
        return meta, path.read_bytes()

    def purge_expired(self, *, now: datetime | None = None) -> int:
        moment = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        rows = self.conn.execute(
            "SELECT blob_id, path FROM blobs WHERE expires_at < ?", (moment,)
        ).fetchall()
        for row in rows:
            Path(row["path"]).unlink(missing_ok=True)
        self.conn.execute("DELETE FROM blobs WHERE expires_at < ?", (moment,))
        return len(rows)

    # ---------------------------------------------------------------- internal
    @staticmethod
    def _row_to_meta(row: sqlite3.Row) -> BlobMeta:
        return BlobMeta(
            blob_id=row["blob_id"],
            tenant_id=row["tenant_id"],
            sha256=row["sha256"],
            mime=row["mime"],
            size=row["size"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            path=row["path"],
        )
