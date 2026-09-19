"""E9-A Worker 安全删除契约测试 (hermetic, 需 test DB)。

契约:
  DELETE /admin/workers/{worker_id}
  - 三张 active lease 表 (cas_jobs / pubchem_jobs / pubchem_identity_jobs)
    存在 status='leased' AND lease_owner=:wid → 409, detail 指明表与条数
  - 三表均无 active lease → 删除成功 (200, worker_clients 行消失)
  - 不存在 → 404
  - completion receipts 不删除; enabled/scopes 原行为不变(runtime 语义另行由
    test_admin_pipeline_a1 覆盖)

运行: . /tmp/hgs_test_env.sh && ./venv/bin/python -m unittest tests.test_admin_worker_delete
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("HGS_DATABASE_URL", os.environ.get("TEST_DATABASE_URL", ""))

try:
    from tests.db_gate import test_db_or_skip  # noqa: E402

    _RAW = test_db_or_skip()
    DB_URL = "postgresql+asyncpg://" + _RAW.split("://", 1)[1].split("?", 1)[0]
except Exception:  # pragma: no cover - 无 test DB 时跳过 DB 用例
    DB_URL = None

RUN = os.urandom(3).hex()
TOKEN_DIGEST = os.urandom(48).hex()  # 每次运行唯一, 避开 token_hash 唯一约束残留


def _engine():
    from sqlalchemy.ext.asyncio import create_async_engine
    return create_async_engine(DB_URL)


async def _make_worker(db, wid: str) -> None:
    from sqlalchemy import text
    await db.execute(text("""
        INSERT INTO maintenance.worker_clients
        (worker_id, display_name, token_hash, token_prefix, scopes, max_lease_jobs)
        VALUES (:wid, :name, decode(:digest, 'hex'), :prefix, CAST(:scopes AS text[]), 4)
    """), {"wid": wid, "name": "del-test", "digest": TOKEN_DIGEST,
           "prefix": "deadbeef", "scopes": ["pubchem", "cas"]})


async def _make_leased_job(db, table: str, wid: str) -> int:
    """造一条 lease_owner=wid 的 leased job(最小合法形状, 测试后清理)。"""
    from sqlalchemy import text
    if table == "cas_jobs":
        jid = (await db.execute(text("""
            INSERT INTO maintenance.cas_jobs (cas_number, status, dedupe_key,
                lease_owner, lease_token_hash, lease_expires_at)
            VALUES (:cas, 'leased', :dk, :wid, decode(:th, 'hex'), now() + interval '10 minutes')
            RETURNING id
        """), {"cas": f"1000-{RUN}-0", "dk": f"dk-cas-{RUN}", "wid": wid,
               "th": "11" * 32})).scalar()
    elif table == "pubchem_jobs":
        jid = (await db.execute(text("""
            INSERT INTO maintenance.pubchem_jobs (query_value, status, dedupe_key,
                lease_owner, lease_token_hash, lease_expires_at)
            VALUES (:qv, 'leased', :dk, :wid, decode(:th, 'hex'), now() + interval '10 minutes')
            RETURNING id
        """), {"qv": f"qv-{RUN}", "dk": f"dk-pb-{RUN}", "wid": wid, "th": "11" * 32})).scalar()
    else:  # pubchem_identity_jobs
        jid = (await db.execute(text("""
            INSERT INTO maintenance.pubchem_identity_jobs
            (chemical_id, evidence_type, evidence_value, evidence_hash, status,
             dedupe_key, lease_owner, lease_token_hash, lease_expires_at)
            VALUES ((SELECT min(id) FROM chemistry.chemicals), 'cas', :ev, :eh,
                    'leased', :dk, :wid, decode(:th, 'hex'),
                    now() + interval '10 minutes')
            RETURNING id
        """), {"ev": f"{RUN}-ev", "eh": f"{RUN}-eh", "dk": f"dk-id-{RUN}",
               "wid": wid, "th": "11" * 32})).scalar()
    return int(jid)


async def _cleanup(wids: list[str], tables: list[str]) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker
    eng = _engine()
    try:
        async with async_sessionmaker(eng, expire_on_commit=False)() as db:
            for t in tables:
                await db.execute(text(
                    f"DELETE FROM maintenance.{t} WHERE lease_owner = ANY(:wids) OR dedupe_key LIKE :pat"
                ), {"wids": wids, "pat": f"dk-%-{RUN}"})
            await db.execute(text(
                "DELETE FROM maintenance.worker_clients WHERE worker_id = ANY(:wids)"
            ), {"wids": wids})
            await db.commit()
    finally:
        await eng.dispose()


async def _call(method: str, path: str):
    import httpx
    from fastapi import FastAPI
    from api.admin import router as admin_router
    from api.core.database import get_db
    from api.core.security import Actor
    from api import admin as admin_module
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    app = FastAPI()
    app.include_router(admin_router, prefix="/api")

    eng = create_async_engine(DB_URL)
    factory = async_sessionmaker(eng, expire_on_commit=False)

    async def _test_db():
        async with factory() as s:
            yield s

    def _admin_actor() -> Actor:
        return Actor(id=0, username="deladmin", display_name="d",
                     email="d@t.example", role="admin", avatar_path=None,
                     auth_kind="session")

    app.dependency_overrides[get_db] = _test_db
    app.dependency_overrides[admin_module.admin] = _admin_actor
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.request(method, f"/api{path}")
            return r.status_code, (r.json() if r.status_code != 204 else None)
    finally:
        await eng.dispose()


@unittest.skipUnless(DB_URL, "需要 test DB")
class WorkerDeleteContractTests(unittest.IsolatedAsyncioTestCase):
    """DELETE /admin/workers/{id}: active lease 拒绝 / 无 lease 成功 / 404。"""

    WID = f"wdel-{RUN}"

    async def asyncSetUp(self):
        import asyncio
        from sqlalchemy.ext.asyncio import async_sessionmaker
        from sqlalchemy import text
        eng = _engine()
        try:
            async with async_sessionmaker(eng, expire_on_commit=False)() as db:
                # 幂等: 上一条用例可能已删除该行(如 delete 成功用例后)
                await db.execute(text(
                    "DELETE FROM maintenance.worker_clients WHERE worker_id=:wid"
                ), {"wid": self.WID})
                await _make_worker(db, self.WID)
                await db.commit()
        finally:
            await eng.dispose()

    async def asyncTearDown(self):
        # 先清 leased job(lease_owner 悬空会触发 lease_shape CHECK + FK SET NULL),
        # 再清 worker 行 — 顺序不可颠倒。
        await _cleanup([self.WID], ["cas_jobs", "pubchem_jobs", "pubchem_identity_jobs"])

    async def _grant_lease(self, table: str) -> int:
        from sqlalchemy.ext.asyncio import async_sessionmaker
        eng = _engine()
        try:
            async with async_sessionmaker(eng, expire_on_commit=False)() as db:
                jid = await _make_leased_job(db, table, self.WID)
                await db.commit()
                return jid
        finally:
            await eng.dispose()

    async def test_1_pubchem_lease_blocks_delete(self):
        await self._grant_lease("pubchem_jobs")
        code, body = await _call("DELETE", f"/admin/workers/{self.WID}")
        self.assertEqual(409, code)
        self.assertIn("pubchem_jobs", body["detail"])
        self.assertIn("不能删除", body["detail"])
        # worker 行仍在
        code2, workers = await _call("GET", "/admin/workers")
        self.assertEqual(200, code2)
        self.assertIn(self.WID, [w["worker_id"] for w in workers])

    async def test_2_cas_lease_blocks_delete(self):
        await self._grant_lease("cas_jobs")
        code, body = await _call("DELETE", f"/admin/workers/{self.WID}")
        self.assertEqual(409, code)
        self.assertIn("cas_jobs", body["detail"])

    async def test_3_identity_lease_blocks_delete(self):
        await self._grant_lease("pubchem_identity_jobs")
        code, body = await _call("DELETE", f"/admin/workers/{self.WID}")
        self.assertEqual(409, code)
        self.assertIn("pubchem_identity_jobs", body["detail"])

    async def test_4_no_lease_deletes(self):
        code, body = await _call("DELETE", f"/admin/workers/{self.WID}")
        self.assertEqual(200, code)
        self.assertTrue(body["deleted"])
        code2, workers = await _call("GET", "/admin/workers")
        self.assertNotIn(self.WID, [w["worker_id"] for w in workers])

    async def test_5_missing_worker_404(self):
        code, body = await _call("DELETE", f"/admin/workers/no-such-{RUN}")
        self.assertEqual(404, code)
        self.assertIn("不存在", body["detail"])

    async def test_6_queued_jobs_do_not_block(self):
        """非 leased 状态(queued)不阻塞删除 — 只挡 active lease。"""
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker
        eng = _engine()
        try:
            async with async_sessionmaker(eng, expire_on_commit=False)() as db:
                await db.execute(text("""
                    INSERT INTO maintenance.pubchem_jobs (query_value, status, dedupe_key)
                    VALUES (:qv, 'queued', :dk)
                """), {"qv": f"qv-{RUN}", "dk": f"dk-pb-{RUN}"})
                await db.commit()
        finally:
            await eng.dispose()
        code, _ = await _call("DELETE", f"/admin/workers/{self.WID}")
        self.assertEqual(200, code)


@unittest.skipUnless(DB_URL, "需要 test DB")
class WorkerListRuntimeProjectionTests(unittest.IsolatedAsyncioTestCase):
    """GET /admin/workers 附带 runtime 投影(复用 pipeline_health, 不另造阈值)。"""

    WID = f"wrt-{RUN}"

    async def test_runtime_field_present(self):
        code, workers = await _call("GET", "/admin/workers")
        self.assertEqual(200, code)
        for w in workers:
            self.assertIn(w["runtime"], ("online", "stale", "offline", "disabled"),
                          f"runtime 投影非法: {w.get('runtime')}")
            self.assertNotIn("token_hash", w)
            self.assertNotIn("token_prefix", w)


if __name__ == "__main__":
    unittest.main()
