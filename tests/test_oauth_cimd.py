"""B (I-072/I-071/I-073) — OAuth Client ID Metadata Document (CIMD) 针对性测试.

覆盖(B6):
1. URL 语法闸: http/无 path/fragment/用户信息/非默认端口/超长 → 拒绝;
2. SSRF: 私网/回环/链路本地/保留/组播解析结果(IPv4+IPv6, 含映射写法)一律拒绝,
   且拒绝发生在建连之前;
3. 拉取消费侧校验: 非 200(含重定向)、超 5KB、非 JSON、非法 JSON → 拒绝;
4. 文档校验: client_id 逐字节一致、redirect_uris 1-10 条、auth method 仅 none
   (private_key_jwt → invalid_client_metadata)、grant/response 规则同 DCR;
5. 缓存: 缓存期内不重复拉取、过期重拉、过期且拉取失败拒绝(不用过期缓存兜底);
6. 正常流程: 拉取 → 授权确认页(host 来源 + localhost 提示) → 换 token → refresh;
7. I-071: 无效 client_id / redirect_uri 未登录时直接得 400 错误页, 不跳登录;
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
# 真库: 缓存 / 正常流程 / I-071 / 来源标记
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
        """I-071: client/redirect 校验先于登录跳转; 无效得 400 错误页。"""

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
