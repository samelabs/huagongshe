"""workapi 契约测试 — 8 端点鉴权与响应形状(回归网, 批次4-2)。

用真实 HMAC 签名头打 TestClient; 断言状态码+响应键, 不断言业务细节。
需要 DB 与 worker_clients 表中注册的测试 client(token_hash)。
"""
import hashlib
import hmac
import json
import os
import time
import unittest
import uuid

from fastapi.testclient import TestClient

# 0909 测试库闸: DB 契约测试必须显式测试库; 未设置则整模块 skip
import unittest as _ut
try:
    from tests.db_gate import test_db_or_skip as _gate
    _gate()
    _GATE_OK = True
except Exception:
    _GATE_OK = False

if _GATE_OK:
    from unittest import mock

    from fastapi import HTTPException

    from api.core.config import settings
    from api.main import app

TOKEN = "it_contract_" + "a" * 32  # >=32字符哑token
WORKER_ID = "it-contract-test-worker"
# T001 scope 面: 身份合法但 scope 不含目标 family 的第二凭据(实测 fail-closed)
TOKEN_CAS = "it_contract_" + "b" * 32
WORKER_ID_CAS = "it-contract-test-worker-cas"


def sign(method: str, path: str, body: bytes, token: str = TOKEN,
         worker_id: str = WORKER_ID, ts: str | None = None,
         nonce: str | None = None):
    ts = ts or str(int(time.time()))
    nonce = nonce or uuid.uuid4().hex
    body_hash = hashlib.sha256(body).hexdigest()
    signed = "\n".join((ts, nonce, method, path, body_hash)).encode()
    sig = hmac.new(token.encode(), signed, hashlib.sha256).hexdigest()
    return {
        "Authorization": f"Bearer {token}",
        "X-Worker-Id": worker_id,
        "X-Work-Timestamp": ts,
        "X-Work-Nonce": nonce,
        "X-Work-Signature": sig,
    }


@_ut.skipUnless(_GATE_OK, "需要测试库 (TEST_DATABASE_URL 过闸)")
class WorkApiContractTests(unittest.TestCase):
    _registered = False

    @classmethod
    def _ensure_registered(cls):
        # 在 TestClient 的 portal loop 里注册(避免跨 event loop 的 engine 连接)
        if cls._registered:
            return
        from api.core.database import async_session
        from sqlalchemy import text

        async def _register():
            async with async_session() as s:
                await s.execute(text("""
                    INSERT INTO maintenance.worker_clients (worker_id, display_name, token_hash, token_prefix, scopes, enabled)
                    VALUES (:wid, 'contract-test', :th, 'it_ct', ARRAY['pubchem','cas'], true)
                    ON CONFLICT (worker_id) DO UPDATE SET token_hash = EXCLUDED.token_hash, enabled = true
                """), {"wid": WORKER_ID, "th": hashlib.sha256(TOKEN.encode()).digest()})
                # T001: scope 面第二凭据(仅 cas) — 身份合法、scope 不含 pubchem
                await s.execute(text("""
                    INSERT INTO maintenance.worker_clients (worker_id, display_name, token_hash, token_prefix, scopes, enabled)
                    VALUES (:wid, 'contract-test-cas', :th, 'it_ctc', ARRAY['cas'], true)
                    ON CONFLICT (worker_id) DO UPDATE SET token_hash = EXCLUDED.token_hash, enabled = true
                """), {"wid": WORKER_ID_CAS,
                       "th": hashlib.sha256(TOKEN_CAS.encode()).digest()})
                await s.commit()

        cls.client.portal.call(_register)
        cls._registered = True

    @classmethod
    def setUpClass(cls):
        cls._cm = TestClient(app)
        cls.client = cls._cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        # 测试凭据自清: 不在生产库留 it-contract-test-worker(2026-08-31 污染事故)
        try:
            # 独立临时 engine(避免与 TestClient portal 的 app engine 跨 loop)
            import asyncio as _aio, os as _os
            from sqlalchemy.ext.asyncio import create_async_engine as _ce
            from sqlalchemy import text as _t
            async def _cleanup():
                _u = __import__("tests.db_gate", fromlist=["require_test_db"]).require_test_db()
                _u = _u.split("?")[0]
                if _u.startswith("postgresql://"):
                    _u = "postgresql+asyncpg://" + _u.split("://", 1)[1]
                tmp = _ce(_u)
                # 先归还测试名下租约(否则 lease_shape CHECK 挡 DELETE), 再删凭据
                async with tmp.begin() as c:
                    await c.execute(_t("""
                        UPDATE maintenance.pubchem_jobs
                        SET status='queued', lease_owner=NULL,
                            lease_token_hash=NULL, lease_expires_at=NULL
                        WHERE lease_owner IN (:w, :w2) AND status='leased'"""),
                        {"w": WORKER_ID, "w2": WORKER_ID_CAS})
                    await c.execute(_t("""
                        UPDATE maintenance.cas_jobs
                        SET status='queued', lease_owner=NULL,
                            lease_token_hash=NULL, lease_expires_at=NULL
                        WHERE lease_owner IN (:w, :w2) AND status='leased'"""),
                        {"w": WORKER_ID, "w2": WORKER_ID_CAS})
                    await c.execute(_t("""
                        UPDATE maintenance.pubchem_identity_jobs
                        SET status='queued', lease_owner=NULL,
                            lease_token_hash=NULL, lease_expires_at=NULL
                        WHERE lease_owner IN (:w, :w2) AND status='leased'"""),
                        {"w": WORKER_ID, "w2": WORKER_ID_CAS})
                    await c.execute(_t(
                        "DELETE FROM maintenance.worker_clients WHERE worker_id IN (:w, :w2)"),
                        {"w": WORKER_ID, "w2": WORKER_ID_CAS})
                await tmp.dispose()
            _aio.new_event_loop().run_until_complete(_cleanup())
        except Exception as exc:  # noqa: BLE001
            print(f"[contract-test] 凭据清理失败(需手工删 {WORKER_ID}): {exc}")
        cls._cm.__exit__(None, None, None)

    def setUp(self):
        self._ensure_registered()

    def _post(self, path: str, payload: dict):
        body = json.dumps(payload).encode()
        headers = sign("POST", path, body)
        headers["Content-Type"] = "application/json"
        return self.client.post(path, content=body, headers=headers)

    # ------------------------------------------------------------------
    # §9 T001: WorkAPI 真实端点 contract 收紧
    # 证据(逐条实测, 非推断): /tmp/e6_t001_probe.txt + /tmp/e6_t001_probe2.txt
    # 收紧原则:
    #   1. 只锁实际存在的 path。旧版测的 /jobs/heartbeat、/jobs/fail、
    #      /cas/jobs/fail 三个 path 根本不存在(真实为 /jobs/error、
    #      /cas/jobs/error, 且 pubchem 无 heartbeat) → 旧断言靠宽泛 tuple
    #      吞掉 404, 等于在测空气。现改为显式断言它们 404。
    #   2. 明确场景锁 exact status + 逐字 detail。
    #   3. scope 面实测: 身份合法但 scope 不含目标 family 时, worker 查询
    #      (scopes @> :scope) 无行 → 401 "unknown or disabled worker"
    #      (fail-closed 收敛进 401, 非 403); 403 仅用于 route 未映射的
    #      fail-closed 分支, 由下方直调 dependency 用例覆盖。
    # ------------------------------------------------------------------
    LEASE_CONFLICT = "lease is missing, expired, or owned by another worker"
    IDENTITY_CONFLICT = (
        "identity lease is missing, expired, or owned by another worker")
    REAL_ENDPOINTS = (
        "/workapi/v1/jobs/lease",
        "/workapi/v1/jobs/complete",
        "/workapi/v1/jobs/error",
        "/workapi/v1/cas/jobs/lease",
        "/workapi/v1/cas/jobs/heartbeat",
        "/workapi/v1/cas/jobs/complete",
        "/workapi/v1/cas/jobs/error",
        "/workapi/v1/identity/jobs/lease",
        "/workapi/v1/identity/jobs/complete",
        "/workapi/v1/identity/jobs/error",
    )
    LEGACY_NONEXISTENT = (
        "/workapi/v1/jobs/heartbeat",
        "/workapi/v1/jobs/fail",
        "/workapi/v1/cas/jobs/fail",
    )
    # 最小合法 body: 字段给全, 否则 422(校验)会掩盖业务 status
    MIN_BODIES = {
        "/workapi/v1/jobs/lease": {"max_jobs": 1, "capabilities": ["pubchem"]},
        "/workapi/v1/jobs/complete": {
            "job_id": 999999999, "lease_token": "z" * 64, "result": {}},
        "/workapi/v1/jobs/error": {
            "job_id": 999999999, "lease_token": "z" * 64, "error_code": "t001"},
        "/workapi/v1/cas/jobs/lease": {"max_jobs": 1, "capabilities": ["cas"]},
        "/workapi/v1/cas/jobs/heartbeat": {
            "job_id": 999999999, "lease_token": "z" * 64},
        "/workapi/v1/cas/jobs/complete": {
            "job_id": 999999999, "lease_token": "z" * 64,
            "result": {"status": "ok"}},
        "/workapi/v1/cas/jobs/error": {
            "job_id": 999999999, "lease_token": "z" * 64, "error_code": "t001"},
        "/workapi/v1/identity/jobs/lease": {
            "max_jobs": 1, "capabilities": ["pubchem"]},
        "/workapi/v1/identity/jobs/complete": {
            "job_id": 999999999, "lease_token": "z" * 64, "cid_list": []},
        "/workapi/v1/identity/jobs/error": {
            "job_id": 999999999, "lease_token": "z" * 64, "error_code": "t001"},
    }

    def test_router_paths_are_exactly_the_ten_real_endpoints(self):
        """结构面: router 的 POST path 集合 == 10 个真实端点(禁幽灵 path)。"""
        import api.workapi as wa
        paths = {r.path for r in wa.router.routes
                 if getattr(r, "methods", None) and "POST" in r.methods}
        self.assertEqual(paths, set(self.REAL_ENDPOINTS))
        # 每个 route 都在 ROUTE_SCOPE 内 → 403 分支不会在生产泄漏
        unmapped = [p for p in paths if ("POST", p) not in wa.ROUTE_SCOPE]
        self.assertEqual(unmapped, [], "存在未映射 scope 的 WorkAPI route")

    def test_legacy_nonexistent_paths_are_404(self):
        """旧 T001 测的三个 path 不存在 — 显式锁 404, 防再次在测空气。"""
        for path in self.LEGACY_NONEXISTENT:
            with self.subTest(path=path):
                r = self._post(path, {"job_id": 999999999})
                self.assertEqual(r.status_code, 404)

    def test_each_real_endpoint_exact_status_and_detail(self):
        """逐端点 exact: 租约端点 200+键集; 未租约终态 409+逐字 detail。"""
        expected = {
            "/workapi/v1/jobs/lease": (200, {"jobs", "retry_after_seconds"}),
            "/workapi/v1/jobs/complete": (409, self.LEASE_CONFLICT),
            "/workapi/v1/jobs/error": (409, self.LEASE_CONFLICT),
            "/workapi/v1/cas/jobs/lease": (200, {"jobs", "retry_after_seconds"}),
            "/workapi/v1/cas/jobs/heartbeat": (409, self.LEASE_CONFLICT),
            "/workapi/v1/cas/jobs/complete": (409, self.LEASE_CONFLICT),
            "/workapi/v1/cas/jobs/error": (409, self.LEASE_CONFLICT),
            "/workapi/v1/identity/jobs/lease": (200, {"jobs", "retry_after_seconds"}),
            "/workapi/v1/identity/jobs/complete": (409, self.IDENTITY_CONFLICT),
            "/workapi/v1/identity/jobs/error": (409, self.IDENTITY_CONFLICT),
        }
        self.assertEqual(set(expected), set(self.REAL_ENDPOINTS))
        for path in self.REAL_ENDPOINTS:
            want_status, want = expected[path]
            with self.subTest(path=path):
                r = self._post(path, self.MIN_BODIES[path])
                self.assertEqual(r.status_code, want_status,
                                 f"{path}: {r.status_code} {r.text[:200]}")
                if isinstance(want, set):
                    self.assertEqual(set(r.json()), want)
                else:
                    self.assertEqual(r.json().get("detail"), want)

    def test_auth_ladder_exact_detail(self):
        """401 阶梯逐字 detail(实测); 每个分支都必须 fail-closed 到 401。"""
        path = "/workapi/v1/jobs/lease"
        body = json.dumps(self.MIN_BODIES[path]).encode()
        good = sign("POST", path, body)
        cases = {}
        cases["missing all headers"] = (
            None, "missing worker token")
        cases["token too short"] = (
            {"Authorization": "Bearer short", "X-Worker-Id": WORKER_ID,
             "X-Work-Timestamp": good["X-Work-Timestamp"],
             "X-Work-Nonce": good["X-Work-Nonce"],
             "X-Work-Signature": good["X-Work-Signature"]},
            "invalid worker identity")
        h = dict(good); h.pop("X-Worker-Id")
        cases["missing worker id"] = (h, "invalid worker identity")
        h = dict(good); h["X-Work-Timestamp"] = "not-a-number"
        cases["bad timestamp"] = (h, "invalid worker timestamp")
        h = dict(good); h["X-Work-Timestamp"] = str(int(time.time()) - 3600)
        cases["timestamp outside skew"] = (h, "expired worker signature")
        h = dict(good); h["X-Work-Nonce"] = "!!not-a-nonce!!"
        cases["bad nonce"] = (h, "invalid worker nonce")
        h = dict(good); h["X-Work-Signature"] = "0" * 64
        cases["bad signature"] = (h, "invalid worker signature")
        h = sign("POST", path, body, worker_id="it-contract-unregistered")
        cases["unregistered worker"] = (h, "unknown or disabled worker")
        for name, (headers, detail) in cases.items():
            with self.subTest(case=name):
                r = self.client.post(path, content=body, headers=headers)
                self.assertEqual(r.status_code, 401, f"{name}: {r.status_code}")
                self.assertEqual(r.json().get("detail"), detail, name)

    def test_scope_mismatch_fails_closed_401(self):
        """身份合法但 scope 不含目标 family → 401(实测收敛, 非 403)。"""
        path = "/workapi/v1/jobs/lease"
        body = json.dumps(self.MIN_BODIES[path]).encode()
        h = sign("POST", path, body, token=TOKEN_CAS, worker_id=WORKER_ID_CAS)
        r = self.client.post(path, content=body, headers=h)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json().get("detail"), "unknown or disabled worker")
        # 反向对照: 同一凭据打 cas 端点应放行(证明拒绝源于 scope 而非凭据无效)
        cpath = "/workapi/v1/cas/jobs/lease"
        cbody = json.dumps(self.MIN_BODIES[cpath]).encode()
        ch = sign("POST", cpath, cbody, token=TOKEN_CAS, worker_id=WORKER_ID_CAS)
        ch["Content-Type"] = "application/json"
        r2 = self.client.post(cpath, content=cbody, headers=ch)
        self.assertEqual(r2.status_code, 200)

    def test_replay_exact_409(self):
        """nonce 复用 → 409 'replayed worker request'(逐字)。"""
        path = "/workapi/v1/jobs/lease"
        body = json.dumps(self.MIN_BODIES[path]).encode()
        headers = sign("POST", path, body)
        headers["Content-Type"] = "application/json"
        first = self.client.post(path, content=body, headers=headers)
        self.assertEqual(first.status_code, 200)
        second = self.client.post(path, content=body, headers=headers)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json().get("detail"), "replayed worker request")

    def test_payload_too_large_exact_413(self):
        """超限 body → 413 'worker payload too large'(逐字, 闸值实测注入)。"""
        path = "/workapi/v1/jobs/lease"
        body = b'{"max_jobs": 1, "capabilities": ["pubchem"]}'
        headers = sign("POST", path, body)
        headers["Content-Type"] = "application/json"
        with mock.patch.object(settings, "worker_max_body_bytes", 8):
            r = self.client.post(path, content=body, headers=headers)
        self.assertEqual(r.status_code, 413)
        self.assertEqual(r.json().get("detail"), "worker payload too large")

    def test_replay_protection_unavailable_exact_503(self):
        """防重放后端故障 → 503(逐字), 不降级为放行也不误报 401/409。"""
        path = "/workapi/v1/jobs/lease"
        body = json.dumps(self.MIN_BODIES[path]).encode()
        headers = sign("POST", path, body)
        headers["Content-Type"] = "application/json"

        class _DeadRedis:
            async def set(self, *a, **k):
                raise RuntimeError("injected redis failure")

        import api.workapi as wa
        with mock.patch.object(wa, "get_cache",
                               mock.AsyncMock(return_value=_DeadRedis())):
            r = self.client.post(path, content=body, headers=headers)
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json().get("detail"),
                         "worker replay protection unavailable")

    def test_unmapped_route_403_fail_closed(self):
        """未映射 route → 403(逐字): 直调 dependency, 不经 router 404 掩盖。"""
        path = "/workapi/v1/not-mapped-by-route-scope"
        body = b"{}"
        h = sign("POST", path, body)

        class _FakeReq:
            def __init__(self):
                self.method = "POST"
                self.url = type("U", (), {"path": path})()

            async def body(self):
                return body

        import api.workapi as wa

        async def _call():
            return await wa.authenticated_worker(
                request=_FakeReq(),
                authorization=h["Authorization"],
                x_worker_id=h["X-Worker-Id"],
                x_work_timestamp=h["X-Work-Timestamp"],
                x_work_nonce=h["X-Work-Nonce"],
                x_work_signature=h["X-Work-Signature"])

        with self.assertRaises(HTTPException) as ctx:
            self.client.portal.call(_call)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail,
                         "workapi route is not mapped to any scope")


if __name__ == "__main__":
    unittest.main()
