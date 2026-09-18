"""Worker trusted write plane 安全测试(0912 审计沉淀, 分支 fix/worker-trusted-plane)。

判别性断言(禁 assertIn 多值白名单):
- Scope gate: 显式 route-family 映射, 未知 path 403 fail-closed
- Auth/replay: 立即 replay 409 / 同 nonce 异 body 409 / 同 nonce 异 path 401 /
  ts 越界 401 / ts 界内 200
- Lease: 跨 worker 409 / 重 lease 后旧 token 409 / 并发双发 complete 恰一个 200
- Revocation: disable → 立即 401(lease/heartbeat/complete); re-enable → 恢复
- Idempotent ack: complete 成功后同 token 重试 → 200 idempotent;
  错 worker / 错 token / 无 receipt → 409
- Post-commit housekeeping: gate/cache 失败不反转成功响应(注入)
- Failure: primary 失败不产 receipt

环境: TEST_DATABASE_URL(test_hgs); Redis 走 api.core.cache 同生产配置。
"""
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
import asyncio
import unittest

import unittest as _ut
try:
    from tests.db_gate import test_db_or_skip as _gate
    _gate()
    _GATE_OK = True
except Exception:
    _GATE_OK = False

if _GATE_OK:
    import httpx

    from api.main import app as _app
    from api.workapi import resolve_route_scope
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def _reset_app_pools():
    """丢弃 app 级连接池中由别的 event loop 建立的连接。

    app engine / redis pool 都是模块级单例; 之前的测试模块在各自的 portal
    loop 上建立过连接, 本模块在自己的 loop 上复用会触发
    "Future attached to a different loop" / "Event loop is closed"。

    Redis 不能用 disconnect(): 旧连接的 writer 绑定在已关闭的 loop 上,
    ``close()`` 直接抛 RuntimeError('Event loop is closed')。改为整体换一个
    新池(构造参数与 api/core/cache.py:12 完全一致), 旧池随引用释放。
    只重置进程内连接池, 不改任何 production 生命周期代码。
    """
    from api.core import cache as _cache
    from api.core.database import engine as _app_engine

    try:
        await _app_engine.dispose()
    except Exception as exc:  # noqa: BLE001 - 旧 loop 的连接无法关闭时直接丢弃
        print(f"[lifecycle] app engine dispose 跳过(旧 loop 连接): "
              f"{type(exc).__name__}: {exc}")
    old_pool = _cache.pool
    _cache.pool = _cache.redis.ConnectionPool.from_url(
        _cache.settings.redis_url, decode_responses=True)
    print(f"[lifecycle] redis pool 已换新 (丢弃旧池 {type(old_pool).__name__})")


class _NoLifespanClient:
    """ASGI 直调客户端(httpx.ASGITransport) — 从不已启动 app lifespan。

    本模块刻意不构造 TestClient: app lifespan 内 mcp_session_lifespan 会
    启动 StreamableHTTPSessionManager, 而该 manager 每实例只允许 run() 一次;
    同进程第二个 TestClient 必抛 "run() can only be called once"。ASGITransport
    只发 http scope, 不发 lifespan scope → 零 startup/shutdown 副作用,
    与 test_workapi_contract 原有的 TestClient/lifespan 并存互不干扰。

    所有请求都跑在调用方给定的同一 event loop 上(与直连 DB 的引擎同 loop),
    不产生跨 loop 的 async client。
    """

    def __init__(self, app, loop):
        self._loop = loop
        self._async = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
            follow_redirects=True,  # 与 starlette TestClient 默认一致
        )

    def post(self, path, *, content=None, headers=None):
        return self._loop.run_until_complete(
            self._async.post(path, content=content, headers=headers))

    def aclose(self):
        self._loop.run_until_complete(self._async.aclose())

TOK = "sec_wtp_" + "9" * 32
TOK_CAS = "sec_wtp_cas_" + "8" * 32
WID = "sec-wtp-worker"
WID_CAS = "sec-wtp-cas-worker"


def _sign(method, path, body, token, wid, ts=None, nonce=None):
    ts = ts or str(int(time.time()))
    nonce = nonce or uuid.uuid4().hex
    signed = "\n".join((ts, nonce, method, path,
                        hashlib.sha256(body).hexdigest())).encode()
    return {
        "Authorization": f"Bearer {token}",
        "X-Worker-Id": wid,
        "X-Work-Timestamp": ts,
        "X-Work-Nonce": nonce,
        "X-Work-Signature": hmac.new(token.encode(), signed, hashlib.sha256).hexdigest(),
        "Content-Type": "application/json",
    }


@_ut.skipUnless(_GATE_OK, "需要测试库 (TEST_DATABASE_URL 过闸)")
class WorkerTrustedPlaneTests(unittest.TestCase):
    eng = None
    LOOP = None

    @classmethod
    def setUpClass(cls):
        cls.LOOP = asyncio.new_event_loop()
        # 静音 httpx 每请求 INFO 日志(CI 输出噪声), 不影响任何断言
        logging.getLogger("httpx").setLevel(logging.WARNING)
        u = os.environ["TEST_DATABASE_URL"].split("?")[0].replace(
            "postgresql://", "postgresql+asyncpg://")
        cls.eng = create_async_engine(u)
        cls.Session = async_sessionmaker(cls.eng, expire_on_commit=False)

        async def _reg():
            async with cls.eng.begin() as c:
                for wid, tok, scopes in (
                        (WID, TOK, "ARRAY['pubchem']"),
                        (WID_CAS, TOK_CAS, "ARRAY['cas']")):
                    await c.execute(text(f"""
                        INSERT INTO maintenance.worker_clients
                          (worker_id,display_name,token_hash,token_prefix,scopes,enabled,created_at)
                        VALUES (:w,'sec-test',:h,:p,{scopes},true,now())
                        ON CONFLICT (worker_id) DO UPDATE SET
                          token_hash=EXCLUDED.token_hash, scopes={scopes},
                          enabled=true, disabled_at=NULL
                    """), {"w": wid, "h": hashlib.sha256(tok.encode()).digest(),
                           "p": tok[:8]})
                await c.execute(text(
                    "DELETE FROM maintenance.workapi_completion_receipts WHERE worker_id LIKE 'sec-wtp-%'"))
                await c.execute(text(
                    "DELETE FROM maintenance.pubchem_jobs WHERE query_value IN ('-42','42')"))
                await c.execute(text(
                    "INSERT INTO chemistry.chemicals (id) VALUES (420042) ON CONFLICT DO NOTHING"))
                await c.execute(text("""
                    INSERT INTO maintenance.pubchem_jobs
                      (chemical_id,query_value,status,priority,dedupe_key)
                    VALUES (420042,'-42','queued',100,'sec-wtp-1')
                """))
        cls.LOOP.run_until_complete(_reg())
        # 先清掉其他测试模块(app engine / redis pool)在别的 event loop 上留下的
        # 连接, 避免本模块请求复用到跨 loop 的 async 连接。
        cls.LOOP.run_until_complete(_reset_app_pools())
        cls.client = _NoLifespanClient(_app, cls.LOOP)

    @classmethod
    def tearDownClass(cls):
        async def _clean():
            async with cls.eng.begin() as c:
                await c.execute(text(
                    "UPDATE maintenance.pubchem_jobs SET status='queued', lease_owner=NULL,"
                    " lease_token_hash=NULL, lease_expires_at=NULL WHERE lease_owner LIKE 'sec-wtp-%'"))
                await c.execute(text(
                    "DELETE FROM maintenance.pubchem_jobs WHERE query_value IN ('-42','42')"))
                await c.execute(text(
                    "DELETE FROM chemistry.chemical_pubchem WHERE chemical_id=420042"))
                await c.execute(text(
                    "DELETE FROM maintenance.workapi_completion_receipts WHERE worker_id LIKE 'sec-wtp-%'"))
                await c.execute(text(
                    "DELETE FROM chemistry.chemicals WHERE id=420042"))
                await c.execute(text(
                    "DELETE FROM maintenance.worker_clients WHERE worker_id LIKE 'sec-wtp-%'"))
            await cls.eng.dispose()
        try:
            cls.LOOP.run_until_complete(_clean())
        finally:
            cls.client.aclose()  # 只关本模块的 ASGI client, 不碰 app lifespan
            cls.LOOP.run_until_complete(_reset_app_pools())
            cls.LOOP.close()

    # ── helpers ──
    def post(self, path, payload, token=TOK, wid=WID, **kw):
        body = json.dumps(payload).encode()
        h = _sign("POST", path, body, token, wid, **kw)
        return self.client.post(path, content=body, headers=h)

    def post_concurrent(self, path, payload, times=2, token=TOK, wid=WID):
        """同一 loop 上并发发同一请求(替代多线程: 单 loop 不可被两线程 run)。"""
        body = json.dumps(payload).encode()
        h = _sign("POST", path, body, token, wid)

        async def _g():
            return await asyncio.gather(*[
                self.client._async.post(path, content=body, headers=h)
                for _ in range(times)])

        return self.LOOP.run_until_complete(_g())

    def _mk_job(self, key):
        async def _m():
            async with self.eng.begin() as c:
                await c.execute(text("""
                    INSERT INTO maintenance.pubchem_jobs
                      (chemical_id,query_value,status,priority,dedupe_key)
                    VALUES (420042,'-42','queued',100,:k)
                """), {"k": key})
        self.LOOP.run_until_complete(_m())

    def _lease_one(self):
        r = self.post("/workapi/v1/jobs/lease", {"max_jobs": 5, "capabilities": ["pubchem"]})
        self.assertEqual(r.status_code, 200, r.text)
        mine = [j for j in r.json()["jobs"] if j["cid"] == -42]
        self.assertTrue(mine, "audit job not leased")
        return mine[0]

    # ── receipt 取证 helpers (family-scoped; CI #73 根因) ──
    def _receipts_for(self, job_id, family="pubchem"):
        """返回 (本 family receipt 行, 同 job_id 的其他 family 撞号行)。"""
        async def _q():
            async with self.eng.connect() as c:
                rows = (await c.execute(text(
                    "SELECT family, job_id, worker_id, terminal_status,"
                    " encode(lease_token_hash,'hex'), completed_at"
                    " FROM maintenance.workapi_completion_receipts"
                    " WHERE family=:f AND job_id=:j ORDER BY completed_at"),
                    {"f": family, "j": job_id})).fetchall()
                foreign = (await c.execute(text(
                    "SELECT family, job_id, worker_id, terminal_status,"
                    " encode(lease_token_hash,'hex'), completed_at"
                    " FROM maintenance.workapi_completion_receipts"
                    " WHERE job_id=:j AND family<>:f ORDER BY completed_at"),
                    {"f": family, "j": job_id})).fetchall()
                return [tuple(r) for r in rows], [tuple(r) for r in foreign]
        return self.LOOP.run_until_complete(_q())

    def _dump_receipt_evidence(self, phase, job, rows, foreign):
        """打印 receipt 取证行(CI #73 所需字段全量)。"""
        import hashlib as _h

        lh = _h.sha256(job["lease_token"].encode()).hexdigest()
        print(f"[receipt-evidence:{phase}] lease family=pubchem job_id={job['job_id']} "
              f"worker_id={WID} lease_token_hash={lh}")
        print(f"[receipt-evidence:{phase}] same(family=pubchem,job_id={job['job_id']}) rows={len(rows)}")
        for r in rows:
            print(f"[receipt-evidence:{phase}]   row family={r[0]} job_id={r[1]} "
                  f"worker_id={r[2]} terminal={r[3]} lease_token_hash={r[4]} completed_at={r[5]}")
        print(f"[receipt-evidence:{phase}] same job_id, other family rows={len(foreign)}")
        for r in foreign:
            print(f"[receipt-evidence:{phase}]   foreign family={r[0]} job_id={r[1]} "
                  f"worker_id={r[2]} terminal={r[3]} lease_token_hash={r[4]} completed_at={r[5]}")

    def _receipts_by_lease(self, job):
        """该 lease(family+job_id+worker_id+token_hash) 在 receipt 表中的行数。"""
        import hashlib as _h

        lh = _h.sha256(job["lease_token"].encode()).digest()
        async def _q():
            async with self.eng.connect() as c:
                return (await c.execute(text(
                    "SELECT count(*) FROM maintenance.workapi_completion_receipts"
                    " WHERE family='pubchem' AND job_id=:j AND worker_id=:w"
                    " AND lease_token_hash=:h"),
                    {"j": job["job_id"], "w": WID, "h": lh})).scalar()
        return self.LOOP.run_until_complete(_q())

    def _job_status(self, job_id):
        async def _q():
            async with self.eng.connect() as c:
                return (await c.execute(text(
                    "SELECT status FROM maintenance.pubchem_jobs WHERE id=:j"),
                    {"j": job_id})).scalar()
        return _q()

    # ════ 1. Scope gate (exact route mapping) ════
    def test_scope_exact_route_matrix(self):
        """10 个 WorkAPI 端点逐条精确映射; 任何非精确 path → None。"""
        cases = [
            ("POST", "/workapi/v1/jobs/lease", "pubchem", True),
            ("POST", "/workapi/v1/jobs/complete", "pubchem", True),
            ("POST", "/workapi/v1/jobs/error", "pubchem", True),
            ("POST", "/workapi/v1/cas/jobs/lease", "cas", True),
            ("POST", "/workapi/v1/cas/jobs/heartbeat", "cas", True),
            ("POST", "/workapi/v1/cas/jobs/complete", "cas", True),
            ("POST", "/workapi/v1/cas/jobs/error", "cas", True),
            ("POST", "/workapi/v1/identity/jobs/lease", "pubchem", True),
            ("POST", "/workapi/v1/identity/jobs/complete", "pubchem", True),
            ("POST", "/workapi/v1/identity/jobs/error", "pubchem", True),
        ]
        for method, path, want, mapped in cases:
            self.assertEqual(resolve_route_scope(method, path), want, path)

    def test_scope_no_family_fallback(self):
        """显式负例: 无精确映射一律 None(禁止 prefix/family 继承)。"""
        negatives = [
            ("POST", "/workapi/v1/jobs/admin"),
            ("POST", "/workapi/v1/cas/jobs/admin"),
            ("POST", "/workapi/v1/identity/jobs/admin"),
            ("POST", "/workapi/v1/jobs/lease/extra"),
            ("POST", "/workapi/v1/jobs"),
            ("POST", "/workapi/v1/jobs/"),
            ("POST", "/workapi/v1/cas/jobs/"),
            ("POST", "/workapi/v2/jobs/lease"),
            ("POST", "/workapi/v2/cas/jobs/lease"),
            ("POST", "/workapi/v2/identity/jobs/lease"),
            ("POST", "/workapi/v3/jobs/complete"),
            ("GET", "/workapi/v1/jobs/lease"),
            ("GET", "/workapi/v1/jobs/complete"),
            ("GET", "/workapi/v1/cas/jobs/lease"),
            ("GET", "/workapi/v1/identity/jobs/lease"),
            ("GET", "/workapi/v1/cas/jobs/heartbeat"),
            ("PUT", "/workapi/v1/jobs/lease"),
            ("POST", "/workapi/v1/admin/jobs/lease"),
            ("POST", "/other/v1/jobs/lease"),
            ("POST", "/workapi/v1/"),
            ("POST", "/"),
        ]
        for method, path in negatives:
            self.assertIsNone(resolve_route_scope(method, path), f"{method} {path}")

    def test_scope_gate_matches_router_registration(self):
        """不变量: 映射表必须与 workapi router 真实注册端点逐条一致。

        任何新增/改名端点若未登记 → 本测试失败(默认拒绝, 不允许静默继承)。
        """
        from api.workapi import router as _r
        registered = {
            (m, r.path)
            for r in _r.routes if hasattr(r, "path")
            for m in getattr(r, "methods", ())
        }
        from api.workapi import ROUTE_SCOPE
        self.assertEqual(set(ROUTE_SCOPE), registered)

    def test_scope_cross_access(self):
        # pubchem token: pubchem PASS
        r = self.post("/workapi/v1/jobs/lease", {"max_jobs": 1, "capabilities": ["pubchem"]})
        self.assertEqual(r.status_code, 200)
        # pubchem token: identity PASS (业务定义: identity 属 pubchem)
        r = self.post("/workapi/v1/identity/jobs/lease", {"max_jobs": 1, "capabilities": ["identity"]})
        self.assertEqual(r.status_code, 200)
        # pubchem token: cas FAIL
        r = self.post("/workapi/v1/cas/jobs/lease", {"max_jobs": 1, "capabilities": ["cas"]})
        self.assertEqual(r.status_code, 401)
        # cas token: cas PASS
        r = self.post("/workapi/v1/cas/jobs/lease", {"max_jobs": 1, "capabilities": ["cas"]},
                      token=TOK_CAS, wid=WID_CAS)
        self.assertEqual(r.status_code, 200)
        # cas token: pubchem FAIL / identity FAIL
        r = self.post("/workapi/v1/jobs/lease", {"max_jobs": 1, "capabilities": ["pubchem"]},
                      token=TOK_CAS, wid=WID_CAS)
        self.assertEqual(r.status_code, 401)
        r = self.post("/workapi/v1/identity/jobs/lease", {"max_jobs": 1, "capabilities": ["identity"]},
                      token=TOK_CAS, wid=WID_CAS)
        self.assertEqual(r.status_code, 401)

    def test_capabilities_cannot_raise_scope(self):
        # pubchem token 声明 capabilities=["cas","identity"] 仍拿不到 cas lease
        r = self.post("/workapi/v1/cas/jobs/lease",
                      {"max_jobs": 1, "capabilities": ["cas", "identity"]})
        self.assertEqual(r.status_code, 401)

    def test_unmapped_route_403_at_auth_layer(self):
        """真实注册但未登记 scope 的 route → 认证层 403(fail-closed)。

        临注册一个 /workapi/v1/jobs/admin 探针(测完移除), 用有效 token +
        有效签名打它: 签名通过后 resolver 返回 None → 必须 403, 不得因
        "/jobs/ 家族" 继承到 pubchem。
        """
        from fastapi import Depends
        from fastapi.routing import APIRoute

        from api.workapi import authenticated_worker

        async def _probe():  # pragma: no cover - 403 在依赖层已拦, 不可达
            return {"unreachable": True}

        # 注意: app.router 末尾挂有 path='' 的 Mount(前端静态), 后加的普通路由会被
        # 它吞成 404 → 必须插到 routes 最前(该 path 与既有路由无冲突)。
        probe = APIRoute("/workapi/v1/jobs/admin", _probe, methods=["POST"],
                         dependencies=[Depends(authenticated_worker)])
        _app.router.routes.insert(0, probe)
        try:
            body = b"{}"
            h = _sign("POST", "/workapi/v1/jobs/admin", body, TOK, WID)
            r = self.client.post("/workapi/v1/jobs/admin", content=body, headers=h)
            self.assertEqual(r.status_code, 403)
            # 未注册的真实路径族 → 路由层 404(同样不可达)
            h2 = _sign("POST", "/workapi/v1/jobs/unknown", body, TOK, WID)
            r2 = self.client.post("/workapi/v1/jobs/unknown", content=body, headers=h2)
            self.assertEqual(r2.status_code, 404)
        finally:
            _app.router.routes.remove(probe)

    # ════ 2. Auth / replay ════
    def test_replay_immediate_409(self):
        body = json.dumps({"max_jobs": 1, "capabilities": ["pubchem"]}).encode()
        h = _sign("POST", "/workapi/v1/jobs/lease", body, TOK, WID)
        r1 = self.client.post("/workapi/v1/jobs/lease", content=body, headers=h)
        self.assertEqual(r1.status_code, 200)
        r2 = self.client.post("/workapi/v1/jobs/lease", content=body, headers=h)
        self.assertEqual(r2.status_code, 409)

    def test_same_nonce_different_body_409(self):
        body1 = json.dumps({"max_jobs": 1, "capabilities": ["pubchem"]}).encode()
        h = _sign("POST", "/workapi/v1/jobs/lease", body1, TOK, WID)
        r1 = self.client.post("/workapi/v1/jobs/lease", content=body1, headers=h)
        self.assertEqual(r1.status_code, 200)  # nonce 先被合法消费
        body2 = json.dumps({"max_jobs": 2, "capabilities": ["pubchem"]}).encode()
        signed = "\n".join((h["X-Work-Timestamp"], h["X-Work-Nonce"], "POST",
                            "/workapi/v1/jobs/lease",
                            hashlib.sha256(body2).hexdigest())).encode()
        h2 = dict(h)
        h2["X-Work-Signature"] = hmac.new(TOK.encode(), signed, hashlib.sha256).hexdigest()
        r = self.client.post("/workapi/v1/jobs/lease", content=body2, headers=h2)
        self.assertEqual(r.status_code, 409)

    def test_same_nonce_different_path_401(self):
        h = _sign("POST", "/workapi/v1/jobs/lease", b'{"max_jobs":1}', TOK, WID)
        body3 = b'{"max_jobs":1}'
        signed = "\n".join((h["X-Work-Timestamp"], h["X-Work-Nonce"], "POST",
                            "/workapi/v1/cas/jobs/lease",
                            hashlib.sha256(body3).hexdigest())).encode()
        h3 = dict(h)
        h3["X-Work-Signature"] = hmac.new(TOK.encode(), signed, hashlib.sha256).hexdigest()
        r = self.client.post("/workapi/v1/cas/jobs/lease", content=body3, headers=h3)
        self.assertEqual(r.status_code, 401)

    def test_timestamp_boundaries(self):
        r = self.post("/workapi/v1/jobs/lease", {"max_jobs": 1, "capabilities": ["pubchem"]},
                      ts=str(int(time.time()) - 301))
        self.assertEqual(r.status_code, 401)
        r = self.post("/workapi/v1/jobs/lease", {"max_jobs": 1, "capabilities": ["pubchem"]},
                      ts=str(int(time.time()) + 301))
        self.assertEqual(r.status_code, 401)
        r = self.post("/workapi/v1/jobs/lease", {"max_jobs": 1, "capabilities": ["pubchem"]},
                      ts=str(int(time.time()) - 299))
        self.assertEqual(r.status_code, 200)

    # ════ 3. Lease invariants ════
    def test_cross_worker_and_released_token(self):
        self._mk_job("sec-wtp-cross")
        j = self._lease_one()
        # 另一 worker(cas worker 即便有 pubchem 数据也无权) 用同 lease_token → 409
        r = self.post("/workapi/v1/jobs/complete",
                      {"job_id": j["job_id"], "lease_token": j["lease_token"], "result": {}},
                      token=TOK_CAS, wid=WID_CAS)
        self.assertEqual(r.status_code, 401)  # cas token 无 pubchem scope
        # 正主 complete 后, 旧 token 重 lease 语义: job 已终态 → 409
        r = self.post("/workapi/v1/jobs/complete",
                      {"job_id": j["job_id"], "lease_token": j["lease_token"], "result": {}})
        self.assertEqual(r.status_code, 200)

    def test_expired_or_wrong_token_409(self):
        self._mk_job("sec-wtp-expired")
        j = self._lease_one()
        wrong = "x" * 64
        r = self.post("/workapi/v1/jobs/complete",
                      {"job_id": j["job_id"], "lease_token": wrong, "result": {}})
        self.assertEqual(r.status_code, 409)

    def test_concurrent_duplicate_complete_single_effect(self):
        self._mk_job("sec-wtp-dup")
        j = self._lease_one()
        payload = {"job_id": j["job_id"], "lease_token": j["lease_token"], "result": {}}
        codes = sorted(r.status_code for r in self.post_concurrent(
            "/workapi/v1/jobs/complete", payload, times=2))
        # 恰一个 primary 成功; 另一个合法终态: 409(receipt 未及可见) /
        # 200 idempotent(P0-2 幂等 ack) / 503(replay-protection Redis 瞬断,
        # fail-closed 在鉴权层挡下, 零业务效应)。数据零重复(下方)才是硬判据。
        self.assertEqual(codes[0], 200)
        self.assertIn(codes[1], (200, 409, 503))

        async def _count():
            async with self.eng.connect() as c:
                n = (await c.execute(text(
                    "SELECT count(*) FROM chemistry.chemical_pubchem WHERE chemical_id=420042"))).scalar()
                return n
        self.assertEqual(self.LOOP.run_until_complete(_count()), 0)  # 空 result 零数据写入

    # ════ 4. Revocation / recovery ════
    def _patch_worker(self, enabled, worker_id=None):
        """走真实 admin patch_worker 生产代码路径(非测试手写 UPDATE)。"""
        from api.admin import WorkerPatchBody, patch_worker

        async def _p():
            async with self.Session() as db:
                return await patch_worker(worker_id or WID,
                                          WorkerPatchBody(enabled=enabled),
                                          actor=None, db=db)
        return self.LOOP.run_until_complete(_p())

    def _worker_row(self, worker_id=None):
        async def _q():
            async with self.eng.connect() as c:
                r = (await c.execute(text(
                    "SELECT enabled, disabled_at FROM maintenance.worker_clients"
                    " WHERE worker_id=:w"), {"w": worker_id or WID})).fetchone()
                return (r[0], r[1])
        return self.LOOP.run_until_complete(_q())

    def test_patch_worker_enabled_tristate(self):
        """P1 三态: false→首次写 now(); true→清 NULL; NULL→逐值完全不动。

        旧实现 disabled_at=CASE WHEN coalesce(:enabled,enabled)=false ...
        在 :enabled IS NULL 且当前 enabled=false 时会重写 now(), 把首次停权
        时刻抹掉 — 本测试逐值锁定四态。
        """
        # true: clean 起点(disabled_at=NULL)
        self._patch_worker(True)
        self.assertEqual(self._worker_row(), (True, None))
        # true → false: 首次停权写 now()
        row = self._patch_worker(False)
        self.assertFalse(row["enabled"])
        e, d1 = self._worker_row()
        self.assertFalse(e)
        self.assertIsNotNone(d1)
        # 重复 disable: 不重置首次 disabled_at
        self._patch_worker(False)
        self.assertEqual(self._worker_row(), (False, d1))
        # enabled=None + 当前 enabled=false: disabled_at 逐值不变
        self._patch_worker(None)
        self.assertEqual(self._worker_row(), (False, d1))
        # false → true: 清 NULL(恢复)
        self._patch_worker(True)
        self.assertEqual(self._worker_row(), (True, None))
        # enabled=None + 当前 enabled=true: 逐值不变
        self._patch_worker(None)
        self.assertEqual(self._worker_row(), (True, None))

    def test_disable_then_reenable(self):
        def set_enabled(flag):
            self._patch_worker(flag)

        self._mk_job("sec-wtp-revoke")
        j = self._lease_one()
        set_enabled(False)
        # 停权后: 新 lease / 已租 heartbeat / 已租 complete 全部立即拒绝
        r = self.post("/workapi/v1/jobs/lease", {"max_jobs": 1, "capabilities": ["pubchem"]})
        self.assertEqual(r.status_code, 401)
        r = self.post("/workapi/v1/cas/jobs/heartbeat",
                      {"job_id": j["job_id"], "lease_token": j["lease_token"]})
        self.assertEqual(r.status_code, 401)
        r = self.post("/workapi/v1/jobs/complete",
                      {"job_id": j["job_id"], "lease_token": j["lease_token"], "result": {}})
        self.assertEqual(r.status_code, 401)
        # 原数据恢复(不建新凭据): re-enable → 原 token 复活
        set_enabled(True)
        r = self.post("/workapi/v1/jobs/lease", {"max_jobs": 1, "capabilities": ["pubchem"]})
        self.assertEqual(r.status_code, 200)

    # ════ 5. Idempotent acknowledgement ════
    def test_idempotent_ack_same_token(self):
        self._mk_job("sec-wtp-idem")
        j = self._lease_one()
        r1 = self.post("/workapi/v1/jobs/complete",
                       {"job_id": j["job_id"], "lease_token": j["lease_token"], "result": {}})
        self.assertEqual(r1.status_code, 200)
        # 新 nonce(新请求), 同 lease_token 重试 → 幂等 ack
        r2 = self.post("/workapi/v1/jobs/complete",
                       {"job_id": j["job_id"], "lease_token": j["lease_token"], "result": {}})
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json().get("idempotent"))

    def test_idempotent_ack_rejects_mismatch(self):
        self._mk_job("sec-wtp-idem2")
        j = self._lease_one()
        r1 = self.post("/workapi/v1/jobs/complete",
                       {"job_id": j["job_id"], "lease_token": j["lease_token"], "result": {}})
        self.assertEqual(r1.status_code, 200)
        # 错 lease_token → 409
        r = self.post("/workapi/v1/jobs/complete",
                      {"job_id": j["job_id"], "lease_token": "y" * 64, "result": {}})
        self.assertEqual(r.status_code, 409)
        # 无 receipt 的 job_id → 409
        r = self.post("/workapi/v1/jobs/complete",
                      {"job_id": 999999999, "lease_token": j["lease_token"], "result": {}})
        self.assertEqual(r.status_code, 409)

    # ════ 6. Post-commit housekeeping 故障注入 ════
    def test_housekeeping_failure_does_not_flip_success(self):
        self._mk_job("sec-wtp-hk")
        j = self._lease_one()
        # 注入: gate_record_success 抛错(模拟 Redis/gate 挂) — 但 monkeypatch 对
        # TestClient 同进程生效
        import api.workapi as wa
        orig = wa.gate_record_success
        async def boom(*a, **k):
            raise RuntimeError("injected redis/gate failure")
        wa.gate_record_success = boom
        try:
            r = self.post("/workapi/v1/jobs/complete",
                          {"job_id": j["job_id"], "lease_token": j["lease_token"], "result": {}})
            self.assertEqual(r.status_code, 200)  # 成功不被反转
            # receipt 已落(primary commit 成功)
            async def _has():
                async with self.eng.connect() as c:
                    return (await c.execute(text(
                        "SELECT count(*) FROM maintenance.workapi_completion_receipts"
                        " WHERE job_id=:j AND family='pubchem'"), {"j": j["job_id"]})).scalar()
            self.assertEqual(self.LOOP.run_until_complete(_has()), 1)
        finally:
            wa.gate_record_success = orig

    # ════ 7. Primary failure → 无 receipt ════
    def test_primary_failure_no_receipt(self):
        self._mk_job("sec-wtp-pf")
        j = self._lease_one()
        # 注入主事务失败: upsert_details 抛错 → complete 5xx → job 留 leased, 无 receipt。
        # 注意 query_value='-42' 非 POSITIVE INT → §2.2 fail-closed 不进写入分支,
        # 因此注入点选 sync_chemical_core 也走不到 — 用 job[1] 行存在但令 record
        # receipt 之前唯一必经的写路径失败: 注入 record_completion_receipt 自身无意义,
        # 选 DELETE 前的业务写: 对空 result 路径直接注入 canonicalize_id。
        import api.workapi as wa
        orig = wa.sync_chemical_core
        async def boom(*a, **k):
            raise RuntimeError("injected primary failure")
        wa.sync_chemical_core = boom
        try:
            # query_value 需为合法正整数才能进写入分支: 该 job '-42' 会 fail-closed
            # 直接出表(无写入)。改用真实合法 cid 的 job 验证 primary failure。
            async def _mk_valid():
                async with self.eng.begin() as c:
                    await c.execute(text("""
                        INSERT INTO maintenance.pubchem_jobs
                          (chemical_id,query_value,status,priority,dedupe_key)
                        VALUES (420042,'42','queued',100,'sec-wtp-pf-valid')
                    """))
            self.LOOP.run_until_complete(_mk_valid())
            r = self.post("/workapi/v1/jobs/lease", {"max_jobs": 5, "capabilities": ["pubchem"]})
            mine = [j for j in r.json()["jobs"] if j["cid"] == 42]
            self.assertTrue(mine)
            j = mine[0]
            payload = {"job_id": j["job_id"], "lease_token": j["lease_token"],
                       "result": {"payload": {"core": {"CID": 42}}}}
            # TestClient 默认把服务端异常 re-raise — 短时关掉 transport 的
            # raise_server_exceptions 拿真实 500 响应
            body_b = json.dumps(payload).encode()
            h = _sign("POST", "/workapi/v1/jobs/complete", body_b, TOK, WID)
            # 客户端 transport 已固定 raise_app_exceptions=False → 真实 500 响应
            r = self.client.post("/workapi/v1/jobs/complete", content=body_b, headers=h)
            self.assertEqual(r.status_code, 500)

            # CI #73 根因定位: 旧断言 "WHERE job_id=:j" 不带 family, 会把其他
            # family(cas) 数字撞号的残留 receipt 计入 → expected 0 / actual 1 假阳性。
            # 现按 (family, job_id) 精确定位, 并单列跨 family 行作为证据。
            pre, foreign_pre = self._receipts_for(j["job_id"])
            self._dump_receipt_evidence("pre", j, pre, foreign_pre)
            self.assertEqual(pre, [], f"请求前本 family 已有 receipt(隔离泄漏): {pre}")
            rows, foreign = self._receipts_for(j["job_id"])
            self._dump_receipt_evidence("post", j, rows, foreign)
            self.assertEqual([tuple(x) for x in rows], [],
                             f"primary 失败后出现本 family receipt: {rows}")
            self.assertEqual(self._receipts_by_lease(j), 0,
                             "本次 lease 的 token 不得出现在任何 receipt 中")
            if foreign:
                print(f"[diag] job_id={j['job_id']} 跨 family 撞号残留: {foreign}")
            js = self.LOOP.run_until_complete(self._job_status(j["job_id"]))
            self.assertEqual(js, "leased")   # job 未错误 terminal
        finally:
            wa.sync_chemical_core = orig
            # job 归还
            async def _release():
                async with self.eng.begin() as c:
                    await c.execute(text(
                        "UPDATE maintenance.pubchem_jobs SET status='queued',"
                        " lease_owner=NULL, lease_token_hash=NULL, lease_expires_at=NULL"
                        " WHERE id=:j"), {"j": j["job_id"]})
            self.LOOP.run_until_complete(_release())

    # ════ E5. Transport neutrality: 409 逐字 detail(真实 app + test_hgs) ════
    # service 抛 neutral(LeaseConflictError), adapter 独占映射 → 既有 409 +
    # 逐字 detail。本段锁"HTTP status/detail 未漂移", 不覆盖 T001 的宽断言面。
    E5_LEASE_DETAIL = "lease is missing, expired, or owned by another worker"

    def test_e5_valid_lease_path_unchanged(self):
        """合法租约路径不受 neutral 化影响(200 + 既有成功体)。"""
        self._mk_job("sec-wtp-e5-ok")
        j = self._lease_one()
        r = self.post("/workapi/v1/jobs/complete",
                      {"job_id": j["job_id"], "lease_token": j["lease_token"],
                       "result": {}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json().get("status"), "ok")

    def test_e5_complete_wrong_owner_lease_exact_409_detail(self):
        """错 owner/token → 409 且 detail 逐字(不是子串匹配)。"""
        self._mk_job("sec-wtp-e5-c1")
        j = self._lease_one()
        r = self.post("/workapi/v1/jobs/complete",
                      {"job_id": j["job_id"], "lease_token": "z" * 64,
                       "result": {}})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"], self.E5_LEASE_DETAIL)

    def test_e5_error_wrong_owner_lease_exact_409_detail(self):
        self._mk_job("sec-wtp-e5-e1")
        j = self._lease_one()
        r = self.post("/workapi/v1/jobs/error",
                      {"job_id": j["job_id"], "lease_token": "z" * 64,
                       "error_code": "E5_NET", "error_detail": "x"})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"], self.E5_LEASE_DETAIL)

    def test_e5_missing_job_exact_409_detail(self):
        """无行 lease → 同一 neutral → 同一 409/detail(与错 owner 无差别)。"""
        r = self.post("/workapi/v1/jobs/complete",
                      {"job_id": 987654321, "lease_token": "z" * 64,
                       "result": {}})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"], self.E5_LEASE_DETAIL)

    def test_e5_cas_heartbeat_exact_409_detail(self):
        """cas 通道同一 neutral 类型(verified_cas_lease)→ 同一 409/detail。"""
        good = "sec-wtp-e5-cas-tok-" + "7" * 32  # lease_token min_length=32
        OTHER_TOKEN = "q" * 64                   # 另一 owner 持有的 token(错 token 用例)
        async def _mk():
            async with self.eng.begin() as c:
                await c.execute(text("""
                    INSERT INTO maintenance.cas_jobs
                      (chemical_id,cas_number,status,priority,dedupe_key,
                       lease_owner,lease_token_hash,lease_expires_at)
                    VALUES (420042,'50-00-0','leased',100,'sec-wtp-e5-cas-ok',
                            :w,:h,now()+interval '10 minutes')
                """), {"w": WID_CAS,
                       "h": hashlib.sha256(good.encode()).digest()})
                await c.execute(text("""
                    INSERT INTO maintenance.cas_jobs
                      (chemical_id,cas_number,status,priority,dedupe_key,
                       lease_owner,lease_token_hash,lease_expires_at)
                    VALUES (420042,'50-00-0','leased',100,'sec-wtp-e5-cas-bad',
                            :w,:h,now()+interval '10 minutes')
                """), {"w": WID_CAS,
                       "h": hashlib.sha256((OTHER_TOKEN).encode()).digest()})
        self.LOOP.run_until_complete(_mk())
        try:
            async def _ids():
                async with self.eng.connect() as c:
                    rows = (await c.execute(text(
                        "SELECT id,dedupe_key FROM maintenance.cas_jobs"
                        " WHERE dedupe_key LIKE 'sec-wtp-e5-cas-%'"))).fetchall()
                return {r[1]: r[0] for r in rows}
            ids = self.LOOP.run_until_complete(_ids())
            ok = self.post("/workapi/v1/cas/jobs/heartbeat",
                           {"job_id": ids["sec-wtp-e5-cas-ok"], "lease_token": good},
                           token=TOK_CAS, wid=WID_CAS)
            self.assertEqual(ok.status_code, 200, ok.text)  # 合法 heartbeat 未变
            r = self.post("/workapi/v1/cas/jobs/heartbeat",
                          {"job_id": ids["sec-wtp-e5-cas-bad"], "lease_token": "z" * 64},
                          token=TOK_CAS, wid=WID_CAS)
            self.assertEqual(r.status_code, 409, r.text)
            self.assertEqual(r.json()["detail"], self.E5_LEASE_DETAIL)
        finally:
            async def _clean():
                async with self.eng.begin() as c:
                    await c.execute(text(
                        "DELETE FROM maintenance.cas_jobs"
                        " WHERE dedupe_key LIKE 'sec-wtp-e5-cas-%'"))
            self.LOOP.run_until_complete(_clean())


if __name__ == "__main__":
    unittest.main()
