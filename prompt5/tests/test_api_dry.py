"""M0 · api 测试：--dry 输出契约、stdlib 冒烟服务真实返回 capabilities。"""

from __future__ import annotations

import contextlib
import io
import json
import threading
import unittest
import urllib.request

from prompt5.api.app import capabilities_payload, main, make_stdlib_server


class DryRunTest(unittest.TestCase):
    def test_dry_prints_capabilities(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(["--dry"])
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["api_version"], "1")
        self.assertEqual(len(payload["capabilities"]), 9)
        self.assertEqual(payload["mcp_tool_count"], 18)
        self.assertGreaterEqual(payload["error_code_count"], 30)

    def test_capability_shape(self) -> None:
        payload = capabilities_payload()
        for item in payload["capabilities"]:
            self.assertEqual(
                set(item), {"op", "version", "status", "ready", "sync", "scopes_required"}
            )
        discovery = next(c for c in payload["capabilities"] if c["op"] == "discovery.v1")
        self.assertEqual(discovery["status"], "stable")
        iterate = next(c for c in payload["capabilities"] if c["op"] == "iterate.v1")
        self.assertEqual(iterate["status"], "planned")


class HttpSmokeTest(unittest.TestCase):
    def test_serves_capabilities_over_http(self) -> None:
        server = make_stdlib_server(port=0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/v1/capabilities", timeout=5
            ) as response:
                self.assertEqual(response.status, 200)
                body = json.loads(response.read().decode("utf-8"))
            self.assertEqual(len(body["capabilities"]), 9)
            self.assertEqual(body["mcp_tool_count"], 18)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
