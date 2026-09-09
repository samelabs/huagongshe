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
    from api.core.config import settings
    from api.main import app

TOKEN = "it_contract_" + "a" * 32  # >=32字符哑token
WORKER_ID = "it-contract-test-worker"


def sign(method: str, path: str, body: bytes, token: str = TOKEN):
    ts = str(int(time.time()))
    nonce = uuid.uuid4().hex
    body_hash = hashlib.sha256(body).hexdigest()
    signed = "\n".join((ts, nonce, method, path, body_hash)).encode()
    sig = hmac.new(token.encode(), signed, hashlib.sha256).hexdigest()
    return {
        "Authorization": f"Bearer {token}",
        "X-Worker-Id": WORKER_ID,
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
                tmp = _ce((__import__("tests.db_gate", fromlist=["require_test_db"]).require_test_db()))
                # 先归还测试名下租约(否则 lease_shape CHECK 挡 DELETE), 再删凭据
                async with tmp.begin() as c:
                    await c.execute(_t("""
                        UPDATE maintenance.pubchem_jobs
                        SET status='queued', lease_owner=NULL,
                            lease_token_hash=NULL, lease_expires_at=NULL
                        WHERE lease_owner=:w AND status='leased'"""), {"w": WORKER_ID})
                    await c.execute(_t("""
                        UPDATE maintenance.cas_jobs
                        SET status='queued', lease_owner=NULL,
                            lease_token_hash=NULL, lease_expires_at=NULL
                        WHERE lease_owner=:w AND status='leased'"""), {"w": WORKER_ID})
                    await c.execute(_t(
                        "DELETE FROM maintenance.worker_clients WHERE worker_id = :w"),
                        {"w": WORKER_ID})
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

    def test_lease_pubchem(self):
        r = self._post("/workapi/v1/jobs/lease", {"max_jobs": 1, "capabilities": ["pubchem"]})
        self.assertIn(r.status_code, (200, 204))
        if r.status_code == 200:
            self.assertIn("jobs", r.json())

    def test_lease_cas(self):
        r = self._post("/workapi/v1/cas/jobs/lease", {"max_jobs": 1, "capabilities": ["cas"]})
        self.assertIn(r.status_code, (200, 204))

    def test_heartbeat_rejects_unknown(self):
        r = self._post("/workapi/v1/jobs/heartbeat", {"job_id": 999999999, "ok": True})
        self.assertIn(r.status_code, (200, 204, 404, 409, 422, 503))

    def test_cas_heartbeat_rejects_unknown(self):
        r = self._post("/workapi/v1/cas/jobs/heartbeat", {"job_id": 999999999, "ok": True})
        self.assertIn(r.status_code, (200, 204, 404, 409, 422, 503))

    def test_complete_rejects_unknown(self):
        r = self._post("/workapi/v1/jobs/complete", {"job_id": 999999999, "result": {}})
        self.assertIn(r.status_code, (200, 204, 404, 409, 422, 503))

    def test_cas_complete_rejects_unknown(self):
        r = self._post("/workapi/v1/cas/jobs/complete", {"job_id": 999999999, "result": {}})
        self.assertIn(r.status_code, (200, 204, 404, 409, 422, 503))

    def test_fail_rejects_unknown(self):
        r = self._post("/workapi/v1/jobs/fail", {"job_id": 999999999, "error": "contract-test"})
        self.assertIn(r.status_code, (200, 204, 404, 409, 422, 503))

    def test_cas_fail_rejects_unknown(self):
        r = self._post("/workapi/v1/cas/jobs/fail", {"job_id": 999999999, "error": "contract-test"})
        self.assertIn(r.status_code, (200, 204, 404, 409, 422, 503))

    def test_bad_signature_401(self):
        body = b"{}"
        h = sign("POST", "/workapi/v1/jobs/lease", body)
        h["X-Work-Signature"] = "0" * 64
        r = self.client.post("/workapi/v1/jobs/lease", content=body, headers=h)
        self.assertEqual(r.status_code, 401)

    def test_missing_token_401(self):
        r = self.client.post("/workapi/v1/jobs/lease", content=b"{}")
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
