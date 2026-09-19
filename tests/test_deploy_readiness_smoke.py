"""E8 readiness / smoke 测试 —— readiness 必须是真 HTTP, 不能是"端口开着/进程存在"。

用本机临时 HTTP stub(真实 socket, 随机端口)证明:
  - 503 / 非 ok JSON / 空响应 → 不算 ready; 200 + {"status": "ok"} → 算 ready;
  - API 代与 web 代(BFF)都要能答, 缺一不算 ready;
  - smoke 只覆盖 readiness + 普通 HTTP + MCP 基本可达, 且 MCP 版本必须等于 VERSION。
不触碰生产端口 / 真实 nginx / PM2。
"""

from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ops.deploy import (  # noqa: E402
    MCP_INITIALIZE_BODY,
    Deployer,
    HttpProber,
    Paths,
    Probe,
    parse_mcp_version,
)
from tests.deploy_fakes import (  # noqa: E402
    FakeProber,
    FakeRunner,
    FakeWorld,
    make_env,
    probe_generation,
    write_active_link,
)


class _StubHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self._respond()

    def do_POST(self) -> None:  # noqa: N802
        self._respond()

    def _respond(self) -> None:
        srv = self.server
        srv.requests.append((self.command, self.path, self.headers.get("Host")))
        body = srv.body.encode("utf-8")
        self.send_response(srv.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # 静音
        return


class StubServer:
    """可改状态的本机 HTTP stub(随机端口)。"""

    def __init__(self, *, status: int = 200, body: str = '{"status": "ok"}') -> None:
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
        self.httpd.status = status
        self.httpd.body = body
        self.httpd.requests = []
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    def set(self, *, status: int, body: str) -> None:
        self.httpd.status = status
        self.httpd.body = body

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ReadinessCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.paths = make_env(self.tmp)
        self.world = FakeWorld()
        self.world.start("blue")
        write_active_link(self.paths, "blue")
        self.addCleanup(self._tmp.cleanup)

    def make(self, *, prober=None, **kw) -> Deployer:
        opts = dict(
            readiness_timeout=0.2,
            readiness_interval=0.02,
            drain_grace=0.0,
            stop_timeout=0.2,
            log=lambda *a, **k: None,
        )
        opts.update(kw)
        return Deployer(
            paths=self.paths,
            runner=FakeRunner(self.world, self.paths),
            prober=prober if prober is not None else HttpProber(self.paths),
            **opts,
        )


class ReadinessTests(ReadinessCase):
    def test_readiness_requires_http_200_not_just_open_port(self) -> None:
        stub = StubServer(status=503, body="")
        self.addCleanup(stub.close)
        d = self.make()
        gen = probe_generation(stub.port, stub.port)

        self.assertFalse(d.wait_ready(gen), "端口开着但 503 → 不算 ready")

        stub.set(status=200, body=json.dumps({"status": "ok"}))
        self.assertTrue(d.wait_ready(gen))
        self.assertTrue(stub.httpd.requests, "readiness 必须真的发 HTTP 请求")
        self.assertEqual(stub.httpd.requests[0][1], "/api/health")

    def test_readiness_rejects_200_without_ok_status(self) -> None:
        stub = StubServer(status=200, body=json.dumps({"status": "degraded"}))
        self.addCleanup(stub.close)
        d = self.make()
        gen = probe_generation(stub.port, stub.port)
        self.assertFalse(d.wait_ready(gen), "非 ok 语义不算 ready")

        stub.set(status=200, body="not-json")
        self.assertFalse(d.wait_ready(gen), "非 JSON 不算 ready")

    def test_readiness_requires_both_api_and_web_generations(self) -> None:
        api = StubServer(status=200, body=json.dumps({"status": "ok"}))
        self.addCleanup(api.close)
        d = self.make()

        api_only = probe_generation(api.port, free_port())
        self.assertFalse(d.wait_ready(api_only), "web 代答不上 → 整代不算 ready")

        web = StubServer(status=200, body=json.dumps({"status": "ok"}))
        self.addCleanup(web.close)
        self.assertTrue(d.wait_ready(probe_generation(api.port, web.port)))
        self.assertEqual(web.httpd.requests[0][1], "/api/health")

    def test_readiness_wait_is_bounded_when_nothing_listens(self) -> None:
        d = self.make(readiness_timeout=0.3)
        started = time.monotonic()
        self.assertFalse(d.wait_ready(probe_generation(free_port(), free_port())))
        self.assertLess(time.monotonic() - started, 3.0)

    def test_probe_reports_error_without_raising(self) -> None:
        probe = HttpProber(self.paths).get(free_port(), "/api/health", timeout=0.2)
        self.assertFalse(probe.ok)
        self.assertTrue(probe.error)


class PublicEntryProbeTests(ReadinessCase):
    def test_public_probe_targets_local_nginx_entry_with_host_header(self) -> None:
        import http.client as http_client

        recorded: dict = {}

        class FakeResponse:
            status = 200

            def read(self) -> bytes:
                return b'{"status": "ok"}'

        class FakeConn:
            def __init__(self, host, port, timeout=None, context=None) -> None:
                recorded["host"] = host
                recorded["port"] = port
                recorded["tls"] = context is not None

            def request(self, method, path, body=None, headers=None) -> None:
                recorded["method"] = method
                recorded["path"] = path
                recorded["headers"] = dict(headers or {})

            def getresponse(self) -> FakeResponse:
                return FakeResponse()

            def close(self) -> None:
                recorded["closed"] = True

        original = http_client.HTTPSConnection
        http_client.HTTPSConnection = FakeConn
        try:
            prober = HttpProber(Paths(public_host="huagongshe.com", public_port=443))
            probe = prober.public_get("/api/health")
        finally:
            http_client.HTTPSConnection = original

        self.assertTrue(probe.ok)
        self.assertEqual(recorded["host"], "127.0.0.1")
        self.assertEqual(recorded["port"], 443)
        self.assertTrue(recorded["tls"])
        self.assertEqual(recorded["path"], "/api/health")
        self.assertEqual(recorded["headers"].get("Host"), "huagongshe.com")

    def test_public_post_sends_initialize_payload(self) -> None:
        prober = FakeProber(self.world)
        payload = json.loads(MCP_INITIALIZE_BODY.decode())
        self.assertEqual(payload["method"], "initialize")
        probe = prober.public_post("/mcp", MCP_INITIALIZE_BODY)
        self.assertTrue(probe.ok)
        self.assertEqual(prober.calls[-1], ("public_post", "/mcp"))


class SmokeTests(ReadinessCase):
    def test_smoke_covers_readiness_ordinary_http_and_mcp(self) -> None:
        d = self.make(prober=FakeProber(self.world))
        smoke = d.smoke()

        self.assertEqual(set(smoke["checks"]), {"readiness", "http", "mcp"})
        self.assertTrue(smoke["ok"], smoke)
        self.assertTrue(all(c["ok"] for c in smoke["checks"].values()))

    def test_smoke_fails_when_mcp_version_differs_from_version_file(self) -> None:
        self.world.version = "9.9.9"
        d = self.make(prober=FakeProber(self.world))
        smoke = d.smoke()

        self.assertFalse(smoke["ok"])
        self.assertTrue(smoke["checks"]["readiness"]["ok"])
        self.assertTrue(smoke["checks"]["http"]["ok"])
        self.assertFalse(smoke["checks"]["mcp"]["ok"])
        self.assertEqual(smoke["checks"]["mcp"]["version"], "9.9.9")

    def test_smoke_fails_when_ordinary_page_is_not_ok(self) -> None:
        d = self.make(prober=FakeProber(self.world, page_status=500))
        smoke = d.smoke()
        self.assertFalse(smoke["ok"])
        self.assertFalse(smoke["checks"]["http"]["ok"])

    def test_smoke_fails_when_page_body_is_empty(self) -> None:
        class EmptyPageProber(FakeProber):
            def public_get(self, path, timeout=None) -> Probe:
                probe = super().public_get(path, timeout)
                if path == "/":
                    return Probe(ok=True, status=200, body="")
                return probe

        d = self.make(prober=EmptyPageProber(self.world))
        smoke = d.smoke()
        self.assertFalse(smoke["checks"]["http"]["ok"])

    def test_smoke_fails_when_mcp_endpoint_is_not_reachable(self) -> None:
        class NoMcpProber(FakeProber):
            def public_post(self, path, body, headers=None, timeout=None) -> Probe:
                return Probe(ok=False, status=502, error="upstream refused")

        d = self.make(prober=NoMcpProber(self.world))
        smoke = d.smoke()
        self.assertFalse(smoke["ok"])
        self.assertFalse(smoke["checks"]["mcp"]["ok"])


class ParseMcpVersionTests(unittest.TestCase):
    def test_parses_sse_and_plain_json(self) -> None:
        sse = 'event: message\ndata: {"result": {"serverInfo": {"version": "1.5.1"}}}\n\n'
        self.assertEqual(parse_mcp_version(sse), "1.5.1")
        plain = json.dumps({"result": {"serverInfo": {"version": "1.5.1"}}})
        self.assertEqual(parse_mcp_version(plain), "1.5.1")

    def test_returns_none_on_garbage(self) -> None:
        self.assertIsNone(parse_mcp_version(""))
        self.assertIsNone(parse_mcp_version("<html>502</html>"))
        self.assertIsNone(parse_mcp_version(json.dumps({"error": {"code": -32601}})))


if __name__ == "__main__":
    unittest.main()
