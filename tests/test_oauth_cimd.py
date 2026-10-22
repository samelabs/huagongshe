"""B (//) — OAuth Client ID Metadata Document (CIMD) 针对性测试.

覆盖(B6):
1. URL 语法闸: http/无 path/fragment/用户信息/非默认端口/超长 → 拒绝;
2. SSRF: 私网/回环/链路本地/保留/组播解析结果(IPv4+IPv6, 含映射写法)一律拒绝,
   且拒绝发生在建连之前;
3. 拉取消费侧校验: 非 200(含重定向)、超 5KB、非 JSON、非法 JSON → 拒绝;
4. 文档校验: client_id 逐字节一致、redirect_uris 1-10 条、auth method 仅 none
   (private_key_jwt → invalid_client_metadata)、grant/response 规则同 DCR;
5. 缓存: 缓存期内不重复拉取、过期重拉、过期且拉取失败拒绝(不用过期缓存兜底);
6. 正常流程: 拉取 → 授权确认页(host 来源 + localhost 提示) → 换 token → refresh;
7. 无效 client_id / redirect_uri 未登录时直接得 400 错误页, 不跳登录;
8. 来源标记: DCR 注册行 source_type='dcr'; 授权管理列表 CIMD 带可信 host。

拉取全部走可注入 fetcher 或打桩(测试不访问外网); DB 用真链测试库。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import unittest
import uuid
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

os.environ.setdefault(
    "HGS_DATABASE_URL",
    "postgresql+asyncpg://oauth:oauth@127.0.0.1:5432/unused",
)

ASYNC_URL = None
try:
    from tests.db_gate import test_db_or_skip
    _raw = test_db_or_skip()
except Exception:
    _raw = None

if _raw:
    _u = urlparse(_raw)
    assert parse_qs(_u.query).get("test_sentinel") in (
        ["hgs-test-db"], ["hgs-ephemeral-db"])
    ASYNC_URL = re.sub(
        r"^postgres(?:ql)?://", "postgresql+asyncpg://", _raw.split("?")[0])

from api.services import oauth as svc
from api.services import oauth_cimd
from api.services.oauth_cimd import FetchedDocument


def _document(client_id: str, **overrides) -> dict:
    doc = {
        "client_id": client_id,
        "client_name": "Agent " + uuid.uuid4().hex[:6],
        "redirect_uris": [f"https://{urlparse(client_id).hostname}/callback"],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
    }
    doc.update(overrides)
    return doc


class _StubFetcher:
    """可注入 fetcher: 记录调用次数, 按队列返回结果或异常。"""

    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[str] = []

    async def __call__(self, url: str) -> FetchedDocument:
        self.calls.append(url)
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _ok_fetch(client_id: str, *, cache_control=None, **overrides) -> FetchedDocument:
    return FetchedDocument(
        status=200,
        content_type="application/json",
        cache_control=cache_control,
        body=json.dumps(_document(client_id, **overrides)).encode(),
    )


def _s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


_PKCE_VERIFIER = "v" * 43
_PKCE_CHALLENGE = _s256(_PKCE_VERIFIER)


async def _no_limit(*args, **kwargs):
    return None


# ---------------------------------------------------------------------------
# 纯函数: URL 语法闸 / IP 判定 / 缓存期
# ---------------------------------------------------------------------------

class CimdUrlSyntaxTests(unittest.TestCase):
    def test_https_url_with_path_is_cimd(self):
        self.assertTrue(oauth_cimd.is_cimd_client_id("https://a.example/c.json"))
        self.assertFalse(oauth_cimd.is_cimd_client_id("http://a.example/c.json"))
        self.assertFalse(oauth_cimd.is_cimd_client_id("hgo_client_x"))

    def test_rejects_missing_path_fragment_userinfo_port(self):
        cases = [
            "https://example.com",                        # 无 path
            "https://example.com/c.json#frag",            # fragment
            "https://user:pw@example.com/c.json",         # 用户信息
            "https://user@example.com/c.json",
            "https://example.com:8443/c.json",            # 非默认端口
            "https://example.com:444/c.json",
            "https://例え.jp/c.json",                      # 非 ASCII
            "https://example.com/" + "a" * 300,           # 超长
        ]
        for value in cases:
            with self.subTest(value=value[:40]):
                with self.assertRaises(svc.OAuthProtocolError) as raised:
                    oauth_cimd.validate_cimd_url(value)
                self.assertEqual(raised.exception.error, "invalid_request")

    def test_accepts_minimal_valid_url(self):
        oauth_cimd.validate_cimd_url("https://example.com/c.json")
        oauth_cimd.validate_cimd_url("https://example.com:443/c.json?x=1")


class IpPolicyTests(unittest.TestCase):
    def test_forbidden_addresses(self):
        for value in (
            "127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1",
            "169.254.169.254", "0.0.0.0", "100.64.0.1", "192.0.2.1",
            "198.18.0.1", "224.0.0.1", "240.0.0.1", "255.255.255.255",
            "::1", "::", "fe80::1", "fd00::1", "ff02::1", "2001:db8::1",
            "::ffff:127.0.0.1", "::ffff:10.0.0.1",       # IPv4-mapped
            "2002:0a00:0001::",                          # 6to4 内嵌 10.0.0.1
        ):
            with self.subTest(ip=value):
                self.assertFalse(oauth_cimd._ip_allowed(value))

    def test_public_addresses_allowed(self):
        for value in ("93.184.216.34", "8.8.8.8", "2606:4700::1111", "1.1.1.1"):
            with self.subTest(ip=value):
                self.assertTrue(oauth_cimd._ip_allowed(value))

    def test_fetch_rejects_any_forbidden_resolution_before_connecting(self):
        async def mixed_resolve(host, port):
            return ["93.184.216.34", "192.168.1.1"]  # 一条私网即整体拒绝

        async def loopback_resolve(host, port):
            return ["127.0.0.1"]

        async def no_connect(*a, **k):
            raise AssertionError("不得向未通过校验的地址发起连接")

        for resolver in (mixed_resolve, loopback_resolve):
            with self.subTest(resolver=resolver.__name__):
                with patch.object(oauth_cimd, "_resolve_addresses", resolver), \
                     patch.object(asyncio, "open_connection", no_connect):
                    with self.assertRaises(svc.OAuthProtocolError) as raised:
                        asyncio.run(oauth_cimd._fetch_document(
                            "https://example.com/c.json"))
                self.assertIn("forbidden address", raised.exception.description)

    def test_slow_dns_resolution_hits_total_deadline(self):
        """慢 DNS 受总截止线约束: 解析挂住 → 到点按拉取超时拒绝, 不无限等。"""
        async def stalled_resolve(host, port):
            await asyncio.sleep(600)

        async def no_connect(*a, **k):
            raise AssertionError("解析未按时完成时不得建连")

        with patch.object(oauth_cimd, "_resolve_addresses", stalled_resolve), \
             patch.object(asyncio, "open_connection", no_connect), \
             patch.object(oauth_cimd, "FETCH_TIMEOUT_SECONDS", 0.2):
            with self.assertRaises(svc.OAuthProtocolError) as raised:
                asyncio.run(oauth_cimd._fetch_document(
                    "https://example.com/c.json"))
        self.assertIn("could not be fetched", raised.exception.description)


class CacheAgeTests(unittest.TestCase):
    def test_default_and_clamping(self):
        self.assertEqual(oauth_cimd.cache_age_seconds(None), 3600)
        self.assertEqual(oauth_cimd.cache_age_seconds("no-cache"), 3600)
        self.assertEqual(oauth_cimd.cache_age_seconds("max-age=10"), 300)
        self.assertEqual(oauth_cimd.cache_age_seconds("max-age=172800"), 86400)
        self.assertEqual(oauth_cimd.cache_age_seconds("max-age=1800"), 1800)
        self.assertEqual(
            oauth_cimd.cache_age_seconds("public, MAX-AGE = 7200"), 7200)


# ---------------------------------------------------------------------------
# 文档校验(纯函数, 不触 DB)
# ---------------------------------------------------------------------------

class DocumentValidationTests(unittest.TestCase):
    URL = "https://agent.example.test/client.json"

    def test_rejects_client_id_mismatch(self):
        doc = _document("https://other.example/client.json")
        with self.assertRaises(svc.OAuthProtocolError) as raised:
            oauth_cimd.validate_cimd_document(self.URL, doc)
        self.assertEqual(raised.exception.error, "invalid_client_metadata")

    def test_rejects_private_key_jwt_and_other_auth_methods(self):
        for method in ("private_key_jwt", "client_secret_basic"):
            with self.subTest(method=method):
                with self.assertRaises(svc.OAuthProtocolError) as raised:
                    oauth_cimd.validate_cimd_document(
                        self.URL, _document(self.URL,
                                            token_endpoint_auth_method=method))
                self.assertEqual(raised.exception.error, "invalid_client_metadata")

    def test_rejects_bad_redirect_uris(self):
        for uris in ([], ["x" * 11], 5, ["javascript:alert(1)"],
                     ["http://remote.example/cb"], [1, 2],
                     ["https://a.example/cb"] * 11):
            with self.subTest(uris=uris):
                with self.assertRaises(svc.OAuthProtocolError):
                    oauth_cimd.validate_cimd_document(
                        self.URL, _document(self.URL, redirect_uris=uris))

    def test_accepts_loopback_http_redirect_uris(self):
        values = oauth_cimd.validate_cimd_document(
            self.URL, _document(self.URL, redirect_uris=["http://localhost:7788/cb"]))
        self.assertEqual(values["redirect_uris"], ["http://localhost:7788/cb"])

    def test_grant_and_response_rules_match_dcr(self):
        with self.assertRaises(svc.OAuthProtocolError):
            oauth_cimd.validate_cimd_document(
                self.URL, _document(self.URL, grant_types=[]))
        with self.assertRaises(svc.OAuthProtocolError):
            oauth_cimd.validate_cimd_document(
                self.URL, _document(self.URL, grant_types=["client_credentials"]))
        with self.assertRaises(svc.OAuthProtocolError):
            oauth_cimd.validate_cimd_document(
                self.URL, _document(self.URL, response_types=["token"]))
        values = oauth_cimd.validate_cimd_document(
            self.URL, _document(self.URL, grant_types=None, response_types=None))
        self.assertEqual(values["grant_types"], ["authorization_code"])
        self.assertEqual(values["response_types"], ["code"])
        values = oauth_cimd.validate_cimd_document(
            self.URL, _document(self.URL, grant_types=[
                "authorization_code", "refresh_token"]))
        self.assertEqual(
            values["grant_types"], ["authorization_code", "refresh_token"])

    def test_name_defaults_to_host_and_truncates(self):
        values = oauth_cimd.validate_cimd_document(
            self.URL, _document(self.URL, client_name=""))
        self.assertEqual(values["client_name"], "agent.example.test")
        values = oauth_cimd.validate_cimd_document(
            self.URL, _document(self.URL, client_name="N" * 500))
        self.assertEqual(len(values["client_name"]), 160)

    def test_client_uri_and_logo_uri_must_be_https(self):
        for key in ("client_uri", "logo_uri"):
            with self.subTest(field=key):
                with self.assertRaises(svc.OAuthProtocolError):
                    oauth_cimd.validate_cimd_document(
                        self.URL, _document(self.URL, **{key: "http://x.example/"}))
        values = oauth_cimd.validate_cimd_document(
            self.URL, _document(self.URL, client_uri="https://agent.example/",
                                logo_uri="https://agent.example/logo.png"))
        self.assertEqual(values["client_uri"], "https://agent.example/")
        self.assertEqual(values["logo_uri"], "https://agent.example/logo.png")

    def test_rejects_non_object_document(self):
        for doc in ([], "x", 5, None):
            with self.subTest(doc=doc):
                with self.assertRaises(svc.OAuthProtocolError):
                    oauth_cimd.validate_cimd_document(self.URL, doc)


class AddressPreferenceTests(unittest.TestCase):
    """1.1: 解析去重不打乱顺序, IPv4 优先(生产机无 IPv6 出口)。"""

    def test_prefer_ipv4_keeps_first_seen_order_within_family(self):
        self.assertEqual(
            oauth_cimd._prefer_ipv4(
                ["2606:4700::1111", "93.184.216.34", "93.184.216.34",
                 "1.2.3.4", "2606:4700::1111"]),
            ["93.184.216.34", "1.2.3.4", "2606:4700::1111"],
        )
        self.assertEqual(oauth_cimd._prefer_ipv4(["::1"]), ["::1"])
        self.assertEqual(oauth_cimd._prefer_ipv4([]), [])


class _FakeStreamReader:
    """最小 HTTP 响应流桩: 逐行头 + 一次性 body。"""

    def __init__(self, lines: list[bytes], body: bytes):
        self._lines = list(lines)
        self._body = body

    async def readline(self):
        return self._lines.pop(0) if self._lines else b""

    async def readexactly(self, n: int) -> bytes:
        value, self._body = self._body[:n], self._body[n:]
        if len(value) < n:
            raise asyncio.IncompleteReadError(value, n)
        return value

    async def read(self, n: int = -1) -> bytes:
        take = self._body if n is None or n < 0 else self._body[:n]
        self._body = self._body[len(take):]
        return take


class _FakeStreamWriter:
    def write(self, data):
        pass

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass


def _ok_response(body: bytes) -> tuple[_FakeStreamReader, _FakeStreamWriter]:
    lines = [
        b"HTTP/1.1 200 OK\r\n",
        b"Content-Type: application/json\r\n",
        f"Content-Length: {len(body)}\r\n".encode(),
        b"\r\n",
    ]
    return _FakeStreamReader(lines, body), _FakeStreamWriter()


class FetchRetryTests(unittest.TestCase):
    """1.1: 逐地址尝试建连, 直到成功或全部失败; 总耗时受 5 秒约束。"""

    URL = "https://example.com/c.json"

    def _fetch(self, open_side_effect, resolved):
        async def fake_resolve(host, port):
            return resolved

        async def go():
            with patch.object(oauth_cimd, "_resolve_addresses", fake_resolve), \
                 patch.object(asyncio, "open_connection", open_side_effect):
                return await oauth_cimd._fetch_document(self.URL)

        return asyncio.run(go())

    def test_first_address_failure_falls_through_to_next(self):
        attempts: list[str] = []

        async def open_conn(address, port, ssl=None, server_hostname=None, limit=None):
            attempts.append(address)
            if len(attempts) == 1:
                raise OSError("connection refused (v6 without egress)")
            return _ok_response(b'{"ok":1}')

        document = self._fetch(open_conn, ["93.184.216.34", "2606:4700::1111"])
        self.assertEqual(document.status, 200)
        self.assertEqual(document.body, b'{"ok":1}')
        self.assertEqual(attempts, ["93.184.216.34", "2606:4700::1111"])

    def test_all_addresses_failing_raises_fetch_error(self):
        async def open_conn(address, port, ssl=None, server_hostname=None, limit=None):
            raise OSError("down")

        with self.assertRaises(svc.OAuthProtocolError) as raised:
            self._fetch(open_conn, ["93.184.216.34", "1.2.3.4"])
        self.assertIn("could not be fetched", raised.exception.description)

    def test_tls_error_counts_as_address_failure_not_fatal(self):
        # ssl.SSLError 是 OSError 子类: 首地址握手失败应尝试下一个地址。
        import ssl as _ssl

        attempts: list[str] = []

        async def open_conn(address, port, ssl=None, server_hostname=None, limit=None):
            attempts.append(address)
            if len(attempts) == 1:
                raise _ssl.SSLError("certificate verify failed")
            return _ok_response(b'{"ok":2}')

        document = self._fetch(open_conn, ["93.184.216.34", "1.2.3.4"])
        self.assertEqual(document.body, b'{"ok":2}')
        self.assertEqual(len(attempts), 2)


class ReadLimitTests(unittest.TestCase):
    """读取上限: 头区块行数/字节数超限、行缓冲 ValueError —— 一律归一为
    协议错误(错误页 + host 失败桶), 不逃成未分类异常。"""

    URL = "https://example.com/c.json"

    def _fetch(self, reader, writer):
        async def fake_open(*args, **kwargs):
            return reader, writer

        async def fake_resolve(host, port):
            return ["203.0.113.10"]

        async def go():
            with patch.object(oauth_cimd, "_resolve_addresses", fake_resolve), \
                 patch.object(asyncio, "open_connection", fake_open):
                return await oauth_cimd._fetch_document(self.URL)

        return asyncio.run(go())

    def test_too_many_header_lines_is_protocol_error(self):
        lines = [b"HTTP/1.1 200 OK\r\n"] + [
            f"X-Pad-{i}: x\r\n".encode() for i in range(oauth_cimd.HEADER_MAX_LINES + 5)
        ] + [b"\r\n"]
        with self.assertRaises(svc.OAuthProtocolError):
            self._fetch(_FakeStreamReader(lines, b"{}"), _FakeStreamWriter())

    def test_header_bytes_overrun_is_protocol_error(self):
        lines = [b"HTTP/1.1 200 OK\r\n"] + [
            b"X-Pad: " + b"y" * 2048 + b"\r\n"
            for _ in range(oauth_cimd.HEADER_MAX_BYTES // 2048 + 1)
        ] + [b"\r\n"]
        with self.assertRaises(svc.OAuthProtocolError):
            self._fetch(_FakeStreamReader(lines, b"{}"), _FakeStreamWriter())

    def test_stream_value_error_is_protocol_error(self):
        class _ExplodingReader(_FakeStreamReader):
            async def readline(self):
                raise ValueError("Separator is not found, and chunk exceed the limit")

        with self.assertRaises(svc.OAuthProtocolError):
            self._fetch(_ExplodingReader([], b""), _FakeStreamWriter())


class BodyReadTests(unittest.TestCase):
    """1.2: 响应分多次到达时必须读到完整 body; 上限与畸形拒绝。"""

    def _read(self, pieces: list[bytes], content_length: str | None, eof=True):
        async def go():
            reader = asyncio.StreamReader(limit=64 * 1024)
            for piece in pieces:
                reader.feed_data(piece)
            if eof:
                reader.feed_eof()
            return await oauth_cimd._read_body(reader, content_length)

        return asyncio.run(go())

    def test_multi_chunk_arrival_with_content_length(self):
        body = b'{"client_name":"' + b"\xe3\x81\x82" * 90 + b'"}'
        self.assertGreater(len(body), 100)
        pieces = [body[i:i + 7] for i in range(0, len(body), 7)]
        self.assertEqual(
            self._read(pieces, str(len(body))), body)

    def test_multi_chunk_arrival_until_eof(self):
        body = b'{"a":' + b"9" * 800 + b"}"
        pieces = [body[i:i + 13] for i in range(0, len(body), 13)]
        self.assertEqual(self._read(pieces, None), body)

    def test_oversized_content_length_rejected_before_read(self):
        with self.assertRaises(svc.OAuthProtocolError) as raised:
            self._read([b"x"], str(oauth_cimd.DOCUMENT_MAX_BYTES + 1))
        self.assertIn("5 KB", raised.exception.description)

    def test_malformed_content_length_rejected(self):
        for value in ("abc", "-5"):
            with self.subTest(cl=value):
                with self.assertRaises(svc.OAuthProtocolError):
                    self._read([b"x"], value)

    def test_truncated_body_before_content_length_rejected(self):
        with self.assertRaises(svc.OAuthProtocolError) as raised:
            self._read([b'{"partial":'], "4096")
        self.assertIn("malformed", raised.exception.description)

    def test_chunked_multi_chunk_body_read_complete(self):
        async def go():
            reader = asyncio.StreamReader(limit=64 * 1024)
            body = b'{"b":' + b"7" * 200 + b"}"
            stream = b""
            for i in range(0, len(body), 30):
                part = body[i:i + 30]
                stream += f"{len(part):x}\r\n".encode() + part + b"\r\n"
            stream += b"0\r\n\r\n"
            for i in range(0, len(stream), 11):
                reader.feed_data(stream[i:i + 11])
            reader.feed_eof()
            return await oauth_cimd._read_chunked(
                reader, oauth_cimd.DOCUMENT_MAX_BYTES + 1)

        self.assertEqual(asyncio.run(go()), b'{"b":' + b"7" * 200 + b"}")


class RateLimitKeyTests(unittest.TestCase):
    """1.3/1.4/URL 桶每次尝试计; host 桶只计失败且拉取前预检;
    登录用户按人分桶; 无 IP 不落共用桶并告警。"""

    URL = "https://agent.example.test/c.json"

    def _ensure(self, fetch_result, *, actor_id, client_ip, check=None):
        calls: list[tuple] = []

        async def recorder(bucket, identity, limit, window):
            calls.append((bucket, identity, limit, window))

        async def go():
            try:
                await oauth_cimd.ensure_client_for_authorize(
                    _SelectOnlyDb(),
                    client_id=self.URL,
                    redirect_uri="https://agent.example.test/callback",
                    actor_id=actor_id,
                    client_ip=client_ip,
                    fetcher=_StubFetcher(fetch_result),
                )
            except Exception:
                # 只关心 enforce 的调用记录: 校验通过后写库被 _SelectOnlyDb
                # 拒绝、或校验失败抛 OAuthProtocolError, 都不影响本测试断言。
                pass

        patches = [patch.object(oauth_cimd.rate_limit, "enforce", recorder)]
        if check is not None:
            async def check_stub(bucket, identity, limit, window):
                return check
            patches.append(patch.object(
                oauth_cimd.rate_limit, "check", check_stub))
        for p in patches:
            p.start()
        try:
            asyncio.run(go())
        finally:
            for p in patches:
                p.stop()
        return calls

    def test_success_counts_url_bucket_only_not_host(self):
        calls = self._ensure(_ok_fetch(self.URL), actor_id=None,
                             client_ip="203.0.113.9", check=True)
        self.assertEqual(calls, [
            ("oauth-cimd-url", self.URL,
             oauth_cimd.FETCH_URL_LIMIT_PER_HOUR, 3600),
            ("oauth-cimd-fetch-anon", "203.0.113.9",
             oauth_cimd.FETCH_ANON_IP_LIMIT_PER_HOUR, 3600),
        ])

    def test_failure_counts_host_bucket(self):
        result = FetchedDocument(status=302, content_type="application/json",
                                 cache_control=None, body=b"{}")
        calls = self._ensure(result, actor_id=None, client_ip="203.0.113.9",
                             check=True)
        self.assertEqual(calls, [
            ("oauth-cimd-url", self.URL,
             oauth_cimd.FETCH_URL_LIMIT_PER_HOUR, 3600),
            ("oauth-cimd-fetch-anon", "203.0.113.9",
             oauth_cimd.FETCH_ANON_IP_LIMIT_PER_HOUR, 3600),
            ("oauth-cimd-host-fail", "agent.example.test",
             oauth_cimd.FETCH_HOST_FAIL_LIMIT_PER_HOUR, 3600),
        ])

    def test_value_error_from_fetcher_counts_host_bucket(self):
        """读取层异常(ValueError)归一为协议错误后同样计入 host 失败桶。"""
        calls = self._ensure(
            ValueError("Separator is not found, and chunk exceed the limit"),
            actor_id=None, client_ip="203.0.113.9", check=True)
        self.assertEqual(calls, [
            ("oauth-cimd-url", self.URL,
             oauth_cimd.FETCH_URL_LIMIT_PER_HOUR, 3600),
            ("oauth-cimd-fetch-anon", "203.0.113.9",
             oauth_cimd.FETCH_ANON_IP_LIMIT_PER_HOUR, 3600),
            ("oauth-cimd-host-fail", "agent.example.test",
             oauth_cimd.FETCH_HOST_FAIL_LIMIT_PER_HOUR, 3600),
        ])

    def test_no_client_ip_skips_anon_bucket_and_logs_warning(self):
        with self.assertLogs("api.services.oauth_cimd", level="WARNING") as logs:
            calls = self._ensure(_ok_fetch(self.URL), actor_id=None,
                                 client_ip=None, check=True)
        self.assertEqual(calls, [
            ("oauth-cimd-url", self.URL,
             oauth_cimd.FETCH_URL_LIMIT_PER_HOUR, 3600),
        ])
        self.assertTrue(any("client IP" in line for line in logs.output))

    def test_logged_in_actor_gets_per_user_bucket(self):
        # 登录用户按人限次(30/h) —— URL 桶挡不住同 host 换路径的横向
        # 铺开, 按人才挡得住; 不再有匿名 IP 桶。
        calls = self._ensure(_ok_fetch(self.URL), actor_id=7, client_ip=None,
                             check=True)
        self.assertEqual(calls, [
            ("oauth-cimd-url", self.URL,
             oauth_cimd.FETCH_URL_LIMIT_PER_HOUR, 3600),
            ("oauth-cimd-fetch-user", "7",
             oauth_cimd.FETCH_USER_LIMIT_PER_HOUR, 3600),
        ])

    def test_host_fail_bucket_full_rejects_without_fetch(self):
        # host 失败桶已满 → 拉取前直接拒绝, 不对外发请求, 不计数。
        fetcher = _StubFetcher(_ok_fetch(self.URL))
        from api.core.rate_limit import RateLimited

        async def go():
            await oauth_cimd.ensure_client_for_authorize(
                _SelectOnlyDb(),
                client_id=self.URL,
                redirect_uri="https://agent.example.test/callback",
                actor_id=7,
                client_ip=None,
                fetcher=fetcher,
            )

        async def recorder(bucket, identity, limit, window):
            return None

        async def check_full(bucket, identity, limit, window):
            # 只对 host 失败桶报满, 其余桶不影响
            return bucket != "oauth-cimd-host-fail"

        with patch.object(oauth_cimd.rate_limit, "enforce", recorder), \
             patch.object(oauth_cimd.rate_limit, "check", check_full):
            with self.assertRaises(RateLimited):
                asyncio.run(go())
        self.assertEqual(fetcher.calls, [], "桶满后不得再发起拉取")

    def test_host_fail_probe_passes_still_fetches(self):
        # 对照: 预检通过时照常拉取(fetcher 被调用)。
        fetcher = _StubFetcher(_ok_fetch(self.URL))

        async def go():
            try:
                await oauth_cimd.ensure_client_for_authorize(
                    _SelectOnlyDb(),
                    client_id=self.URL,
                    redirect_uri="https://agent.example.test/callback",
                    actor_id=None,
                    client_ip="203.0.113.9",
                    fetcher=fetcher,
                )
            except Exception:
                pass

        async def recorder(bucket, identity, limit, window):
            return None

        async def check_ok(bucket, identity, limit, window):
            return True

        with patch.object(oauth_cimd.rate_limit, "enforce", recorder), \
             patch.object(oauth_cimd.rate_limit, "check", check_ok):
            asyncio.run(go())
        self.assertEqual(fetcher.calls, [self.URL])


# ---------------------------------------------------------------------------
# 拉取消费侧校验(对任何 fetcher 一致, 不触网)
# ---------------------------------------------------------------------------

class _SelectOnlyDb:
    """SELECT 返回空行(视为无缓存), INSERT/UPDATE 即失败(校验通过不得写库)。"""

    class _Result:
        def mappings(self):
            class _M:
                @staticmethod
                def first():
                    return None
            return _M()

    async def execute(self, statement, params=None):
        head = str(statement).lstrip().upper()[:6]
        if head.startswith(("INSERT", "UPDATE")):
            raise AssertionError("校验失败不得写库")
        return self._Result()

    async def commit(self):
        return None


class FetchConsumptionTests(unittest.TestCase):
    def _run(self, fetch_result):
        async def go():
            return await oauth_cimd.ensure_client_for_authorize(
                _SelectOnlyDb(),
                client_id="https://agent.example.test/c.json",
                redirect_uri="https://agent.example.test/callback",
                actor_id=None,
                client_ip="203.0.113.9",
                fetcher=_StubFetcher(fetch_result),
            )
        with patch.object(oauth_cimd.rate_limit, "enforce", _no_limit):
            return asyncio.run(go())

    def test_rejects_redirect_status(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                result = FetchedDocument(status=status, content_type="application/json",
                                         cache_control=None, body=b"{}")
                with self.assertRaises(svc.OAuthProtocolError) as raised:
                    self._run(result)
                self.assertIn("Redirects are not followed",
                              raised.exception.description)

    def test_rejects_oversized_body(self):
        big = FetchedDocument(status=200, content_type="application/json",
                              cache_control=None,
                              body=b'{"x":"' + b"a" * (oauth_cimd.DOCUMENT_MAX_BYTES + 1) + b'"}')
        with self.assertRaises(svc.OAuthProtocolError) as raised:
            self._run(big)
        self.assertIn("5 KB", raised.exception.description)

    def test_rejects_non_json_content_type(self):
        result = FetchedDocument(status=200, content_type="text/html",
                                 cache_control=None, body=b"<html></html>")
        with self.assertRaises(svc.OAuthProtocolError):
            self._run(result)

    def test_rejects_invalid_json_body(self):
        result = FetchedDocument(status=200, content_type="application/json",
                                 cache_control=None, body=b"not json {")
        with self.assertRaises(svc.OAuthProtocolError):
            self._run(result)


# ---------------------------------------------------------------------------
# 真库: 缓存 / 正常流程 / / 来源标记
# ---------------------------------------------------------------------------

if ASYNC_URL:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from fastapi.responses import HTMLResponse, RedirectResponse

    from api.core.security import Actor
    import api.oauth as oauth_adapter

    class _DbTestCase(unittest.IsolatedAsyncioTestCase):
        async def asyncSetUp(self):
            self.engine = create_async_engine(ASYNC_URL)
            self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
            self.tag = uuid.uuid4().hex[:10]

        async def asyncTearDown(self):
            await self.engine.dispose()

    @unittest.skipUnless(ASYNC_URL, "测试库闸")
    class CimdFlowDbTests(_DbTestCase):
        async def asyncSetUp(self):
            await super().asyncSetUp()
            self.host = f"agent-{self.tag}.example.test"
            self.client_id = f"https://{self.host}/client.json"
            self.redirect_uri = f"https://{self.host}/callback"
            async with self.engine.begin() as conn:
                self.user_id = int((await conn.execute(text("""
                    INSERT INTO community.users(username,email,password_hash,display_name)
                    VALUES (:u,:e,'x','CIMD Tester') RETURNING id
                """), {
                    "u": f"cimd_{self.tag}", "e": f"cimd_{self.tag}@example.test",
                })).scalar_one())

        async def asyncTearDown(self):
            async with self.engine.begin() as conn:
                await conn.execute(text(
                    "DELETE FROM community.oauth_clients WHERE client_id=:c"),
                    {"c": self.client_id})
                await conn.execute(text(
                    "DELETE FROM community.users WHERE id=:i"), {"i": self.user_id})
            await super().asyncTearDown()

        async def test_full_flow_authorize_exchange_refresh(self):
            fetcher = _StubFetcher(_ok_fetch(self.client_id, cache_control="max-age=3600"))
            async with self.Session() as db:
                view = await oauth_cimd.ensure_client_for_authorize(
                    db, client_id=self.client_id, redirect_uri=self.redirect_uri,
                    actor_id=self.user_id, client_ip=None, fetcher=fetcher)
            self.assertEqual(view["host"], self.host)
            self.assertEqual(view["source_type"], "cimd")
            self.assertEqual(fetcher.calls, [self.client_id])

            async with self.Session() as db:
                row = (await db.execute(text(
                    "SELECT source_type,client_name,metadata_fetched_at,"
                    "metadata_cache_until FROM community.oauth_clients"
                    " WHERE client_id=:c"), {"c": self.client_id})).mappings().first()
            self.assertEqual(row["source_type"], "cimd")
            self.assertIsNotNone(row["metadata_fetched_at"])
            self.assertIsNotNone(row["metadata_cache_until"])

            # 授权确认 → code → token → refresh
            async with self.Session() as db:
                pending = await svc.begin_authorization(
                    db, user_id=self.user_id, client_id=self.client_id,
                    redirect_uri=self.redirect_uri, response_type="code",
                    scope="read reaction:write", state="s1",
                    code_challenge=_PKCE_CHALLENGE, code_challenge_method="S256",
                    resource=svc.mcp_resource_url())
            self.assertEqual(pending["client_name"], row["client_name"])
            async with self.Session() as db:
                redirect = await svc.complete_authorization(
                    db, user_id=self.user_id, request_id=pending["request_id"],
                    approve=True)
            code = parse_qs(urlparse(redirect).query)["code"][0]

            async with self.Session() as db:
                tokens = await svc.exchange_authorization_code(
                    db, client_id=self.client_id, code=code,
                    redirect_uri=self.redirect_uri,
                    code_verifier=_PKCE_VERIFIER,
                    resource=svc.mcp_resource_url())
            self.assertTrue(tokens["access_token"].startswith("hgo_at_"))
            self.assertTrue(tokens["refresh_token"].startswith("hgo_rt_"))

            async with self.Session() as db:
                refreshed = await svc.refresh_access_token(
                    db, client_id=self.client_id,
                    refresh_token=tokens["refresh_token"], scope="read",
                    resource=svc.mcp_resource_url())
            self.assertTrue(refreshed["access_token"].startswith("hgo_at_"))

        async def test_cache_window_skips_refetch_and_expiry_refetches(self):
            fetcher = _StubFetcher(
                _ok_fetch(self.client_id, cache_control="max-age=3600"),
                _ok_fetch(self.client_id, cache_control="max-age=3600"),
            )
            async with self.Session() as db:
                await oauth_cimd.ensure_client_for_authorize(
                    db, client_id=self.client_id, redirect_uri=self.redirect_uri,
                    actor_id=self.user_id, client_ip=None, fetcher=fetcher)
            # 缓存期内: 不再拉取
            async with self.Session() as db:
                await oauth_cimd.ensure_client_for_authorize(
                    db, client_id=self.client_id, redirect_uri=self.redirect_uri,
                    actor_id=self.user_id, client_ip=None, fetcher=fetcher)
            self.assertEqual(len(fetcher.calls), 1)

            # 过期: 重新拉取
            async with self.Session() as db:
                await db.execute(text(
                    "UPDATE community.oauth_clients"
                    " SET metadata_cache_until=now()-interval '1 second'"
                    " WHERE client_id=:c"), {"c": self.client_id})
                await db.commit()
            async with self.Session() as db:
                await oauth_cimd.ensure_client_for_authorize(
                    db, client_id=self.client_id, redirect_uri=self.redirect_uri,
                    actor_id=self.user_id, client_ip=None, fetcher=fetcher)
            self.assertEqual(len(fetcher.calls), 2)

        async def test_expired_and_fetch_failure_rejects_without_stale_fallback(self):
            fetcher = _StubFetcher(
                _ok_fetch(self.client_id, cache_control="max-age=60"),
                svc.OAuthProtocolError("invalid_request", "fetch failed"),
            )
            async with self.Session() as db:
                await oauth_cimd.ensure_client_for_authorize(
                    db, client_id=self.client_id, redirect_uri=self.redirect_uri,
                    actor_id=self.user_id, client_ip=None, fetcher=fetcher)
            async with self.Session() as db:
                await db.execute(text(
                    "UPDATE community.oauth_clients"
                    " SET metadata_cache_until=now()-interval '1 second'"
                    " WHERE client_id=:c"), {"c": self.client_id})
                await db.commit()
            with self.assertRaises(svc.OAuthProtocolError) as raised:
                async with self.Session() as db:
                    await oauth_cimd.ensure_client_for_authorize(
                        db, client_id=self.client_id,
                        redirect_uri=self.redirect_uri,
                        actor_id=self.user_id, client_ip=None, fetcher=fetcher)
            self.assertIn("fetch failed", raised.exception.description)

        async def test_redirect_uri_not_in_document_rejected(self):
            fetcher = _StubFetcher(_ok_fetch(self.client_id))
            with self.assertRaises(svc.OAuthProtocolError) as raised:
                async with self.Session() as db:
                    await oauth_cimd.ensure_client_for_authorize(
                        db, client_id=self.client_id,
                        redirect_uri="https://evil.example/callback",
                        actor_id=self.user_id, client_ip=None, fetcher=fetcher)
            self.assertEqual(raised.exception.error, "invalid_request")
            self.assertIn("redirect_uri", raised.exception.description)

        async def test_list_connections_carries_trusted_host(self):
            fetcher = _StubFetcher(_ok_fetch(self.client_id))
            async with self.Session() as db:
                await oauth_cimd.ensure_client_for_authorize(
                    db, client_id=self.client_id, redirect_uri=self.redirect_uri,
                    actor_id=self.user_id, client_ip=None, fetcher=fetcher)
                await svc._issue_token_pair(
                    db, user_id=self.user_id, client_id=self.client_id,
                    scopes=("read",), resource=svc.mcp_resource_url(),
                    issue_refresh=True)
                connections = await svc.list_connections(db, user_id=self.user_id)
            mine = [c for c in connections if c["client_id"] == self.client_id]
            self.assertEqual(len(mine), 1)
            self.assertEqual(mine[0]["client_host"], self.host)
            for c in connections:
                if not c["client_id"].startswith("https://"):
                    self.assertIsNone(c["client_host"])

        async def test_dcr_registration_is_tagged_dcr(self):
            async with self.Session() as db:
                registered = await svc.register_client(
                    db, redirect_uris=["https://chatgpt.com/callback"],
                    client_name="DCR " + self.tag,
                    token_endpoint_auth_method="none",
                    grant_types=["authorization_code", "refresh_token"],
                    response_types=["code"], application_type="web")
                row = (await db.execute(text(
                    "SELECT source_type FROM community.oauth_clients"
                    " WHERE client_id=:c"),
                    {"c": registered["client_id"]})).scalar_one()
                await db.execute(text(
                    "DELETE FROM community.oauth_clients WHERE client_id=:c"),
                    {"c": registered["client_id"]})
                await db.commit()
            self.assertEqual(row, "dcr")

    @unittest.skipUnless(ASYNC_URL, "测试库闸")
    class AuthorizeOrderTests(_DbTestCase):
        """client/redirect 校验先于登录跳转; 无效得 400 错误页。"""

        class _Url:
            def __init__(self, query):
                self.query = query

        class _Request:
            def __init__(self):
                self.url = AuthorizeOrderTests._Url("client_id=x")
                self.headers = {}

        async def _authorize(self, *, client_id, redirect_uri, actor=None):
            async with self.Session() as db:
                return await oauth_adapter.authorize(
                    request=self._Request(),
                    client_id=client_id,
                    redirect_uri=redirect_uri,
                    response_type="code",
                    scope="read",
                    state="s",
                    code_challenge="x" * 43,
                    code_challenge_method="S256",
                    resource=svc.mcp_resource_url(),
                    actor=actor,
                    db=db,
                )

        async def test_unknown_client_anonymous_gets_error_page_not_login(self):
            response = await self._authorize(
                client_id=f"hgo_client_missing_{uuid.uuid4().hex[:8]}",
                redirect_uri="https://chatgpt.com/callback", actor=None)
            self.assertIsInstance(response, HTMLResponse)
            self.assertEqual(response.status_code, 400)
            body = response.body.decode()
            self.assertIn("client_id", body)
            self.assertNotIn("/login", body)

        async def test_http_url_client_id_is_not_cimd(self):
            # http:// 开头不按 CIMD 处理: 走登记查询 → 未知客户端 → 错误页。
            response = await self._authorize(
                client_id="http://agent.example/client.json",
                redirect_uri="https://agent.example/callback", actor=None)
            self.assertIsInstance(response, HTMLResponse)
            self.assertEqual(response.status_code, 400)

        async def test_unregistered_redirect_uri_gets_error_page(self):
            client_id = f"hgo_client_errpg_{self.tag}"
            async with self.Session() as db:
                await db.execute(text("""
                    INSERT INTO community.oauth_clients(
                        client_id,client_name,redirect_uris,source_type)
                    VALUES (:c,'Err Page Test',
                            ARRAY['https://ok.example/callback'],'registered')
                """), {"c": client_id})
                await db.commit()
            try:
                response = await self._authorize(
                    client_id=client_id,
                    redirect_uri="https://attacker.example/callback",
                    actor=None)
            finally:
                async with self.Session() as db:
                    await db.execute(text(
                        "DELETE FROM community.oauth_clients WHERE client_id=:c"),
                        {"c": client_id})
                    await db.commit()
            self.assertEqual(response.status_code, 400)
            self.assertIn("redirect_uri", response.body.decode())

        async def test_cimd_fetch_failure_anonymous_gets_error_page(self):
            cid = f"https://fail-{self.tag}.example.test/c.json"

            async def failing(url):
                raise svc.OAuthProtocolError(
                    "invalid_request",
                    "Client ID Metadata Document could not be fetched.")

            with patch.object(oauth_cimd, "_fetch_document", failing), \
                 patch.object(oauth_cimd.rate_limit, "enforce", _no_limit):
                response = await self._authorize(
                    client_id=cid, redirect_uri="https://x.example/callback",
                    actor=None)
            self.assertEqual(response.status_code, 400)
            self.assertIn("client_id", response.body.decode())

        async def test_cimd_value_error_gets_error_page(self):
            cid = f"https://verr-{self.tag}.example.test/c.json"

            async def exploding(url):
                raise ValueError("Separator is not found, and chunk exceed the limit")

            with patch.object(oauth_cimd, "_fetch_document", exploding), \
                 patch.object(oauth_cimd.rate_limit, "enforce", _no_limit):
                response = await self._authorize(
                    client_id=cid, redirect_uri="https://x.example/callback",
                    actor=None)
            self.assertEqual(response.status_code, 400)
            self.assertIn("client_id", response.body.decode())

        async def test_valid_client_anonymous_redirects_to_login(self):
            client_id = f"hgo_client_login_{self.tag}"
            async with self.Session() as db:
                await db.execute(text("""
                    INSERT INTO community.oauth_clients(
                        client_id,client_name,redirect_uris,source_type)
                    VALUES (:c,'Login Redirect Test',
                            ARRAY['https://ok.example/callback'],'registered')
                """), {"c": client_id})
                await db.commit()
            try:
                response = await self._authorize(
                    client_id=client_id,
                    redirect_uri="https://ok.example/callback",
                    actor=None)
            finally:
                async with self.Session() as db:
                    await db.execute(text(
                        "DELETE FROM community.oauth_clients WHERE client_id=:c"),
                        {"c": client_id})
                    await db.commit()
            self.assertIsInstance(response, RedirectResponse)
            self.assertIn("/login", response.headers["location"])

        async def test_valid_cimd_logged_in_shows_host_and_localhost_note(self):
            host = f"agent-{self.tag}.example.test"
            cid = f"https://{host}/client.json"
            username = f"consent_{self.tag}"
            async with self.Session() as db:
                user_id = int((await db.execute(text("""
                    INSERT INTO community.users(username,email,password_hash,display_name)
                    VALUES (:u,:u||'@example.test','x','Consent Tester') RETURNING id
                """), {"u": username})).scalar_one())
                await db.commit()
            actor = Actor(user_id, username, "Consent Tester",
                          f"{username}@example.test", "member", None, "session")

            async def ok_fetch(url):
                return _ok_fetch(cid, redirect_uris=["http://localhost:7788/callback"])

            try:
                with patch.object(oauth_cimd, "_fetch_document", ok_fetch), \
                     patch.object(oauth_cimd.rate_limit, "enforce", _no_limit):
                    response = await self._authorize(
                        client_id=cid, redirect_uri="http://localhost:7788/callback",
                        actor=actor)
                self.assertEqual(response.status_code, 200)
                body = response.body.decode()
                self.assertIn(f"from {host}", body)
                self.assertIn("returned to an application on this machine", body)
            finally:
                async with self.Session() as db:
                    await db.execute(text(
                        "DELETE FROM community.users WHERE id=:i"), {"i": user_id})
                    await db.execute(text(
                        "DELETE FROM community.oauth_clients WHERE client_id=:c"),
                        {"c": cid})
                    await db.commit()


if __name__ == "__main__":
    unittest.main()
