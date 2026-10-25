"""M6 · 安全基线：SSRF 守卫与回调签名。"""

from __future__ import annotations

import pytest

from prompt5.security.signing import SigningError, sign_event, verify_event
from prompt5.security.ssrf import SSRFError, validate_callback_url


class TestSSRF:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/hook",
            "http://10.1.2.3/hook",
            "http://192.168.1.1/hook",
            "http://169.254.169.254/latest/meta-data",
            "http://localhost:8080/hook",
            "http://metadata.google.internal/hook",
            "file:///etc/passwd",
            "ftp://example.com/hook",
        ],
    )
    def test_blocks_dangerous(self, url: str) -> None:
        with pytest.raises(SSRFError):
            validate_callback_url(url)

    def test_allows_public(self) -> None:
        assert validate_callback_url("https://example.com/hook") == "https://example.com/hook"

    def test_allowlist_bypasses_dns(self) -> None:
        assert validate_callback_url(
            "http://127.0.0.1/hook", allowlist=["127.0.0.1"]
        ) == "http://127.0.0.1/hook"

    def test_blocked_port(self) -> None:
        with pytest.raises(SSRFError):
            validate_callback_url("https://example.com:6379/hook")


class TestSigning:
    def test_roundtrip(self) -> None:
        event = {"event": "task.state_changed", "data": {"task_id": "tk-1"}}
        signed = sign_event(event, "secret", timestamp=1000)
        assert verify_event(signed, "secret", now=1100) is True

    def test_tampered_body_rejected(self) -> None:
        signed = sign_event({"event": "x"}, "secret", timestamp=1000)
        with pytest.raises(SigningError):
            verify_event({**signed, "event": "y"}, "secret", now=1000)

    def test_wrong_secret_rejected(self) -> None:
        signed = sign_event({"event": "x"}, "secret", timestamp=1000)
        with pytest.raises(SigningError):
            verify_event(signed, "other", now=1000)

    def test_expired_rejected(self) -> None:
        signed = sign_event({"event": "x"}, "secret", timestamp=1000)
        with pytest.raises(SigningError):
            verify_event(signed, "secret", now=99999)

    def test_missing_fields_rejected(self) -> None:
        with pytest.raises(SigningError):
            verify_event({"event": "x"}, "secret")

    def test_signature_excludes_itself(self) -> None:
        signed = sign_event({"event": "x", "signature": "bogus"}, "secret", timestamp=1000)
        assert verify_event({**signed, "signature": signed["signature"]}, "secret", now=1000) is True
