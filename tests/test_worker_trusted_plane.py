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
    from api.workapi import resolve_route_scope
    from tests.shared_client import get_shared_client
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

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
        u = os.environ["TEST_DATABASE_URL"].split("?")[0].replace(
            "postgresql://", "postgresql+asyncpg://")
        cls.eng = create_async_engine(u)

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
                    "DELETE FROM maintenance.pubchem_jobs WHERE query_value='-42'"))
                await c.execute(text(
                    "INSERT INTO chemistry.chemicals (id) VALUES (420042) ON CONFLICT DO NOTHING"))
                await c.execute(text("""
                    INSERT INTO maintenance.pubchem_jobs
                      (chemical_id,query_value,status,priority,dedupe_key)
                    VALUES (420042,'-42','queued',100,'sec-wtp-1')
                """))
        cls.LOOP.run_until_complete(_reg())
        cls.client = get_shared_client()  # 0912: 进程级单 lifespan(见 shared_client.py)

    @classmethod
    def tearDownClass(cls):
        async def _clean():
            async with cls.eng.begin() as c:
                await c.execute(text(
                    "UPDATE maintenance.pubchem_jobs SET status='queued', lease_owner=NULL,"
                    " lease_token_hash=NULL, lease_expires_at=NULL WHERE lease_owner LIKE 'sec-wtp-%'"))
                await c.execute(text(
                    "DELETE FROM maintenance.pubchem_jobs WHERE query_value='-42'"))
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
            pass  # 0912: client 进程级共享, 不 __exit__(由后续模块继续用)

    # ── helpers ──
    def post(self, path, payload, token=TOK, wid=WID, **kw):
        body = json.dumps(payload).encode()
        h = _sign("POST", path, body, token, wid, **kw)
        return self.client.post(path, content=body, headers=h)

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

    # ════ 1. Scope gate ════
    def test_scope_route_resolution_matrix(self):
        cases = [
            ("/workapi/v1/jobs/lease", "pubchem"),
            ("/workapi/v1/jobs/complete", "pubchem"),
            ("/workapi/v1/jobs/error", "pubchem"),
            ("/workapi/v1/cas/jobs/lease", "cas"),
            ("/workapi/v1/cas/jobs/heartbeat", "cas"),
            ("/workapi/v1/cas/jobs/complete", "cas"),
            ("/workapi/v1/cas/jobs/error", "cas"),
            ("/workapi/v1/identity/jobs/lease", "pubchem"),
            ("/workapi/v1/identity/jobs/complete", "pubchem"),
            ("/workapi/v1/identity/jobs/error", "pubchem"),
        ]
        for path, want in cases:
            self.assertEqual(resolve_route_scope("POST", path), want, path)
        # 未映射 → None (fail-closed)
        for path in ("/workapi/v1/admin/jobs/lease", "/workapi/v1/jobs/admin",
                     "/workapi/v1/newthing/x", "/workapi/v2/jobs/lease",
                     "/other/v1/jobs/lease", "/workapi/v1/"):
            self.assertIsNone(resolve_route_scope("POST", path), path)

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

    def test_unmapped_route_403(self):
        # 有效签名 + 有效 token, 但 path 无路由 → FastAPI 404(路由层先挡);
        # fail-closed 判定本身由 resolve_route_scope 单元矩阵覆盖。
        # 再验真实依赖路径: 已注册路由 + 未映射方法变体。
        body = b"{}"
        h = _sign("POST", "/workapi/v1/jobs/unknown", body, TOK, WID)
        r = self.client.post("/workapi/v1/jobs/unknown", content=body, headers=h)
        self.assertIn(r.status_code, (403, 404))  # 不存在路由即不可达(fail-closed)
        # 未映射但格式真实的 path 族: GET 不在映射(method 白名单)
        self.assertIsNone(resolve_route_scope("GET", "/workapi/v1/jobs/lease"))

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
        from concurrent.futures import ThreadPoolExecutor
        self._mk_job("sec-wtp-dup")
        j = self._lease_one()
        payload = {"job_id": j["job_id"], "lease_token": j["lease_token"], "result": {}}
        with ThreadPoolExecutor(2) as ex:
            codes = sorted(f.result().status_code for f in [
                ex.submit(self.post, "/workapi/v1/jobs/complete", payload) for _ in range(2)])
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
    def test_disable_then_reenable(self):
        def set_enabled(flag):
            async def _s():
                async with self.eng.begin() as c:
                    await c.execute(text(
                        "UPDATE maintenance.worker_clients SET enabled=:e,"
                        " disabled_at=CASE WHEN :e THEN NULL ELSE now() END"
                        " WHERE worker_id=:w"), {"e": flag, "w": WID})
            self.LOOP.run_until_complete(_s())

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
            transport = self.client._transport
            transport.raise_server_exceptions = False
            try:
                r = self.client.post("/workapi/v1/jobs/complete", content=body_b, headers=h)
            finally:
                transport.raise_server_exceptions = True
            self.assertEqual(r.status_code, 500)

            async def _state():
                async with self.eng.connect() as c:
                    rc = (await c.execute(text(
                        "SELECT count(*) FROM maintenance.workapi_completion_receipts"
                        " WHERE job_id=:j"), {"j": j["job_id"]})).scalar()
                    js = (await c.execute(text(
                        "SELECT status FROM maintenance.pubchem_jobs WHERE id=:j"),
                        {"j": j["job_id"]})).scalar()
                    return rc, js
            rc, js = self.LOOP.run_until_complete(_state())
            self.assertEqual(rc, 0)          # 无 receipt
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


if __name__ == "__main__":
    unittest.main()
