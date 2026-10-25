"""M3 · 材料接入测试：blob 落盘/哈希/限额/租户隔离/TTL + API 路由。"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from prompt5.api.app import build_fastapi_app
from prompt5.blobs import BlobError, BlobStore
from prompt5.store.migrate import init_db


@pytest.fixture()
def store(tmp_path):
    conn = init_db(":memory:")
    try:
        yield BlobStore(conn, tmp_path / "blobs", max_bytes=32, quota_bytes=64, ttl_days=30)
    finally:
        conn.close()


class TestBlobStore:
    def test_put_and_get(self, store: BlobStore) -> None:
        meta = store.put("t-1", b"hello", "text/plain")
        assert meta.sha256 == hashlib.sha256(b"hello").hexdigest()
        assert meta.blob_id.startswith("bl-")
        assert meta.size == 5
        fetched_meta, content = store.get("t-1", meta.blob_id)
        assert content == b"hello"
        assert fetched_meta.mime == "text/plain"

    def test_dedupe_same_content(self, store: BlobStore) -> None:
        first = store.put("t-1", b"same", "text/plain")
        second = store.put("t-1", b"same", "text/plain")
        assert first.blob_id == second.blob_id

    def test_mime_allowlist(self, store: BlobStore) -> None:
        with pytest.raises(BlobError) as excinfo:
            store.put("t-1", b"x", "application/x-msdownload")
        assert excinfo.value.code == "E_BLOB_MIME"
        assert excinfo.value.status == 415

    def test_size_limit(self, store: BlobStore) -> None:
        with pytest.raises(BlobError) as excinfo:
            store.put("t-1", b"x" * 33, "text/plain")
        assert excinfo.value.code == "E_BLOB_TOO_LARGE"
        assert excinfo.value.status == 413

    def test_tenant_quota(self, store: BlobStore) -> None:
        store.put("t-1", b"a" * 32, "text/plain")
        store.put("t-1", b"b" * 32, "text/plain")
        with pytest.raises(BlobError) as excinfo:
            store.put("t-1", b"c" * 1, "text/plain")
        assert excinfo.value.code == "E_BLOB_QUOTA"

    def test_cross_tenant_denied(self, store: BlobStore) -> None:
        meta = store.put("t-1", b"secret", "text/plain")
        with pytest.raises(BlobError) as excinfo:
            store.get("t-2", meta.blob_id)
        assert excinfo.value.code == "E_SCOPE"
        assert excinfo.value.status == 403

    def test_missing_tenant(self, store: BlobStore) -> None:
        with pytest.raises(BlobError) as excinfo:
            store.put("", b"x", "text/plain")
        assert excinfo.value.code == "E_AUTH_IDENTITY_MISMATCH"

    def test_purge_expired(self, store: BlobStore) -> None:
        meta = store.put("t-1", b"old", "text/plain")
        store.conn.execute("UPDATE blobs SET expires_at='2000-01-01T00:00:00+00:00' WHERE blob_id=?", (meta.blob_id,))
        assert store.purge_expired() == 1
        with pytest.raises(BlobError):
            store.get("t-1", meta.blob_id)


class TestBlobApi:
    @pytest.fixture()
    def client(self, tmp_path):
        app = build_fastapi_app(db_path=":memory:", blob_root=tmp_path / "blobs", max_blob_bytes=64)
        return TestClient(app)

    def test_upload_and_download(self, client: TestClient) -> None:
        response = client.post(
            "/v1/blobs",
            content=b"col1,col2\n1,2\n",
            headers={"x-tenant-id": "t-1", "x-blob-mime": "text/csv"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["content_hash"] == hashlib.sha256(b"col1,col2\n1,2\n").hexdigest()
        assert payload["size"] == len(b"col1,col2\n1,2\n")

        download = client.get(f"/v1/blobs/{payload['blob_id']}", headers={"x-tenant-id": "t-1"})
        assert download.status_code == 200
        assert download.content == b"col1,col2\n1,2\n"

    def test_missing_tenant_rejected(self, client: TestClient) -> None:
        response = client.post("/v1/blobs", content=b"x", headers={"x-blob-mime": "text/plain"})
        assert response.status_code == 401
        assert response.json()["error_code"] == "E_AUTH_IDENTITY_MISMATCH"

    def test_bad_mime(self, client: TestClient) -> None:
        response = client.post(
            "/v1/blobs", content=b"x", headers={"x-tenant-id": "t-1", "x-blob-mime": "video/mp4"}
        )
        assert response.status_code == 415

    def test_cross_tenant_download(self, client: TestClient) -> None:
        uploaded = client.post(
            "/v1/blobs", content=b"x", headers={"x-tenant-id": "t-1", "x-blob-mime": "text/plain"}
        ).json()
        response = client.get(f"/v1/blobs/{uploaded['blob_id']}", headers={"x-tenant-id": "t-2"})
        assert response.status_code == 403
