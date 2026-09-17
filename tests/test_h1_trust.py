"""H1 方案 D 集成测试: 普通 API 无 internal privilege。

核心断言:
- loopback 不再是 authorization evidence(public_or_actor 不读 Request/client.host)
- PubChem refresh 是 use-case policy(allow_refresh 参数), 不是 transport privilege
- 结构检索登录墙 / CAS 限流 / admin/current_actor/current_session 不受影响
- Worker WorkAPI HMAC 契约不动
- BFF inbound x-hgs-* 不转发(静态代码审计)

全部只跑 test_hgs, 经 db_gate。
"""

from __future__ import annotations

import inspect
import os
import re
import unittest

os.environ.setdefault("HGS_DATABASE_URL", os.environ.get("TEST_DATABASE_URL", ""))
try:
    from tests.db_gate import test_db_or_skip  # noqa: E402
    DB_URL = test_db_or_skip()
    DB_URL = "postgresql+asyncpg://" + DB_URL.split("://", 1)[1]
    DB_URL = DB_URL.split("?", 1)[0]
except Exception:
    DB_URL = None

from fastapi import HTTPException

import api.routes as routes
import api.enrichment as enrichment_router
from api.core import security
from api.core.rate_limit import is_loopback_host
from api.services import enrichment as enrichment_service
from api.services import search as search_service


RUN = "h1d"


class PublicOrActorSemanticsTests(unittest.TestCase):
    """A/B/C/E: 匿名公共读不需要 loopback privilege; 结构墙保持。"""

    def test_a_public_or_actor_reads_no_request_state(self):
        """A/E: dependency 不读 Request/client.host —— localhost 与公网匿名等价。"""
        sig = str(inspect.signature(security.public_or_actor))
        self.assertNotIn("request", sig.lower())
        body = inspect.getsource(security.public_or_actor).split('"""')[-1]
        self.assertNotIn("client.host", body)
        self.assertNotIn("is_loopback", body)
        self.assertNotIn("Request", body.replace("request", "REQUEST_X"))
        # 行为: 纯透传 optional_actor, 无 401 分支
        self.assertIn("return actor", body)
        self.assertNotIn("HTTPException", body)
        self.assertNotIn("raise", body)

    def test_a_anonymous_loopback_and_public_are_identical(self):
        """E: localhost 本身不获得额外权限 —— dependency 输出与来源无关,
        匿名(无 cookie/token)在 loopback 与公网同为 actor=None 放行读。"""
        # dependency 纯函数化后, 匿名即 None; 不存在 loopback 专属分支
        self.assertIsNone(asyncio_run_none(security.public_or_actor, None))
        self.assertTrue(callable(security.public_or_actor))

    def test_b_anonymous_exact_search_allowed(self):
        """B: exact 匿名照旧 —— 登录墙只拦 mode!=exact。"""
        src = inspect.getsource(routes.search)
        self.assertIn('if mode != "exact" and actor is None', src)

    def test_c_anonymous_structure_search_still_401(self):
        """C: 结构检索(子结构/相似度)匿名仍 401, H1 不因 public read 开放。"""
        async def go():
            # 直接以 actor=None 走 search 的墙分支语义
            # (墙在函数体内: mode!=exact and actor is None → 401)
            src = routes.search
            self.assertIsNotNone(src)
        # 墙契约由源码断言锁定(与 test_search 一致口径)
        src = inspect.getsource(routes.search)
        m = re.search(r'if mode != "exact" and actor is None:\s*\n\s*raise HTTPException\((\d+)', src)
        self.assertIsNotNone(m, "结构墙必须存在且 fail-closed")
        self.assertEqual(m.group(1), "401")

    def test_d_authenticated_structure_search_allowed(self):
        """D: actor 非 None 时墙不触发(条件短路), 既有行为。"""
        src = inspect.getsource(routes.search)
        self.assertIn('mode != "exact" and actor is None', src)


class RefreshUseCasePolicyTests(unittest.TestCase):
    """F/G/H: allow_refresh 语义。"""

    def test_f_g_refresh_is_use_case_policy_not_transport(self):
        """F/G: enqueue_chemical_if_needed 不读 client.host/loopback;
        详情端点显式 allow_refresh=True; priority 80=actor / 50=匿名。"""
        full = inspect.getsource(enrichment_service.enqueue_chemical_if_needed)
        body = full.split('"""', 2)[2]  # 剥 docstring, 只查代码
        self.assertNotIn("is_loopback_host", body)
        self.assertNotIn("client.host", body)
        self.assertNotIn("request.client", body)
        self.assertIn("allow_refresh: bool", full)
        self.assertIn("if not allow_refresh:", body)
        # 两个详情调用点(G2.4B: chemical_detail 编排下沉 services/chemicals)
        from api.services import chemicals as chemicals_service
        for endpoint in (chemicals_service.get_chemical_detail,
                         enrichment_router.chemical_details):
            esrc = inspect.getsource(endpoint)
            self.assertIn("allow_refresh=True", esrc)
        self.assertIn(
            "priority=80 if actor is not None else 50",
            inspect.getsource(routes.chemical_detail),
        )

    def test_h_allow_refresh_false_zero_enqueue(self):
        """H: allow_refresh=False → stale 时零 enqueue, 返回 needs_refresh=True。"""
        import asyncio
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import text as sql_text
        from sqlalchemy.ext.asyncio import create_async_engine

        async def go():
            engine = create_async_engine(DB_URL)
            try:
                async with engine.begin() as db:
                    row = (await db.execute(sql_text("""
                        SELECT c.id, c.pubchem_cid, cp.fetched_at
                        FROM chemistry.chemicals c
                        LEFT JOIN chemistry.chemical_pubchem cp
                          ON cp.chemical_id=c.id
                        WHERE c.pubchem_cid IS NOT NULL
                          AND (cp.fetched_at IS NULL
                               OR cp.fetched_at < now() - interval '200 days')
                        LIMIT 1
                    """))).fetchone()
                if row is None:
                    self.skipTest("test_hgs 无 stale 样本行")
                chemical_id = row[0]
                async with engine.begin() as db:
                    before = (await db.execute(sql_text(
                        "SELECT count(*) FROM maintenance.pubchem_jobs "
                        "WHERE chemical_id=:c AND request_context->>'reason'='chemical_details'"
                    ), {"c": chemical_id})).scalar()
                async with engine.begin() as db:
                    details, job_id, needs = await enrichment_service.enqueue_chemical_if_needed(
                        db, chemical_id, allow_refresh=False,
                    )
                async with engine.begin() as db:
                    after = (await db.execute(sql_text(
                        "SELECT count(*) FROM maintenance.pubchem_jobs "
                        "WHERE chemical_id=:c AND request_context->>'reason'='chemical_details'"
                    ), {"c": chemical_id})).scalar()
                self.assertIsNone(job_id, "allow_refresh=False 不得 enqueue")
                self.assertTrue(needs, "stale 行应报 needs_refresh")
                self.assertEqual(before, after, "pubchem_jobs 零新增")
            finally:
                await engine.dispose()


        asyncio.run(go())

    def test_f_public_anonymous_refresh_enqueues(self):
        """F: 匿名(无 actor)详情读驱动回补仍按产品策略入队(行为不变,
        依据已从 loopback 换为 use-case)。以 stale 行直调验证 priority=50 路径。"""
        import asyncio
        from sqlalchemy import text as sql_text
        from sqlalchemy.ext.asyncio import create_async_engine

        async def go():
            engine = create_async_engine(DB_URL)
            try:
                async with engine.begin() as db:
                    row = (await db.execute(sql_text("""
                        SELECT c.id FROM chemistry.chemicals c
                        LEFT JOIN chemistry.chemical_pubchem cp
                          ON cp.chemical_id=c.id
                        WHERE c.pubchem_cid IS NOT NULL
                          AND (cp.fetched_at IS NULL
                               OR cp.fetched_at < now() - interval '200 days')
                          AND NOT EXISTS (
                              SELECT 1 FROM maintenance.pubchem_jobs j
                              WHERE j.chemical_id=c.id)
                        LIMIT 1
                    """))).fetchone()
                if row is None:
                    self.skipTest("无可用样本行")
                chemical_id = row[0]
                async with engine.begin() as db:
                    details, job_id, needs = await enrichment_service.enqueue_chemical_if_needed(
                        db, chemical_id, allow_refresh=True, priority=50,
                    )
                self.assertIsNotNone(job_id, "产品策略允许 → 应 enqueue")
                # 清理本测试产生的 job
                engine2 = create_async_engine(DB_URL)
                async with engine2.begin() as db:
                    await db.execute(sql_text(
                        "DELETE FROM maintenance.pubchem_jobs WHERE id=:j"
                    ), {"j": job_id})
                await engine2.dispose()
            finally:
                await engine.dispose()
        asyncio.run(go())


def asyncio_run_none(fn, arg):
    """辅助: public_or_actor(actor=None) 直调。"""
    import asyncio
    return asyncio.run(fn(arg))


class InvariantsTests(unittest.TestCase):
    """I/J/K: 限流/会话/Worker 契约不变。"""

    def test_i_cas_anonymous_global_budget_unchanged(self):
        """行为契约(0915 改写): 不再审计源码字面 `enforce(...)` — 函数局部
        alias 名不是 contract。直接驱动 run_search_query 的 CAS-miss 分支,
        断言落进 rate_limit 的 (bucket, identity, limit, window):
        anonymous → cas-search-fetch / anonymous-global / 30 / 60;
        authenticated → cas-search-fetch / actor id / 10 / 60。
        """
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from api.core import rate_limit

        cas_query = "7732-18-5"  # 合法 CAS 形态; chemicals 命中 mocked 为空 → miss 分支

        def run(actor_id):
            calls: list[tuple] = []

            async def consume(bucket, identity, limit, window_seconds):
                calls.append((bucket, identity, limit, window_seconds))
                return 1, 0, True

            db = MagicMock()
            db.execute = AsyncMock(return_value=MagicMock(scalar=lambda: 0))
            db.rollback = AsyncMock()
            db.commit = AsyncMock()
            with patch.object(rate_limit, "consume", consume), \
                 patch.object(search_service, "fetch_chemicals", new=AsyncMock(return_value=[])), \
                 patch.object(search_service, "run_name_search", new=AsyncMock(return_value=([], False))), \
                 patch.object(search_service, "reaction_lookup", new=AsyncMock(return_value=[])):
                result = asyncio.run(search_service.run_search_query(
                    db, cas_query, "exact", None, 1, 30, 0, actor_id=actor_id,
                ))
            return calls, result

        calls, _ = run(actor_id=None)
        cas_calls = [c for c in calls if c[0] == "cas-search-fetch"]
        self.assertEqual(
            [(c[1], c[2], c[3]) for c in cas_calls],
            [("anonymous-global", 30, 60)],
            "匿名 CAS miss 必须落 cas-search-fetch / anonymous-global / 30 / 60",
        )

        calls, _ = run(actor_id=12345)
        cas_calls = [c for c in calls if c[0] == "cas-search-fetch"]
        self.assertEqual(
            [(c[1], c[2], c[3]) for c in cas_calls],
            [("12345", 10, 60)],
            "鉴权 CAS miss 必须落 cas-search-fetch / actor id / 10 / 60",
        )

    def test_j_session_and_admin_dependencies_unchanged(self):
        from api import admin, users
        self.assertIn("Depends(current_session)", inspect.getsource(admin.admin))
        for endpoint in (users.update_profile, users.create_token):
            self.assertIn("Depends(current_session)", inspect.getsource(endpoint))
        src = inspect.getsource(security.current_actor)
        self.assertIn("401", src)

    def test_k_worker_hmac_contract_unchanged(self):
        import api.workapi as workapi
        src = inspect.getsource(workapi.authenticated_worker)
        for token in ("x_worker_id", "x_work_timestamp", "x_work_nonce",
                      "x_work_signature", "Bearer "):
            self.assertIn(token, src)
        self.assertNotIn("is_loopback", src)
        self.assertNotIn("client.host", src)

    def test_l_bff_strips_inbound_x_hgs_headers(self):
        """L: 静态代码审计 —— BFF 对 inbound x-hgs-* 一律不转发。"""
        route = os.path.join(os.path.dirname(__file__), "..", "web", "app",
                             "api", "[...path]", "route.ts")
        with open(route, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('lower.startsWith("x-hgs-")', src)
        self.assertIn("transport proxy", src)
        self.assertNotIn("T0", src)

    def test_no_loopback_authorization_remains(self):
        """收口: 生产 api/ 内 is_loopback_host 零调用方(仅 rate_limit 定义)。"""
        import subprocess
        root = os.path.join(os.path.dirname(__file__), "..")
        out = subprocess.run(
            ["grep", "-rn", "is_loopback_host", "--include=*.py", "api/"],
            capture_output=True, text=True, cwd=root,
        ).stdout.strip().splitlines()
        producers = [l for l in out if "rate_limit.py" not in l]
        self.assertEqual(producers, [], f"残留 authorization 依赖: {producers}")


if __name__ == "__main__":
    unittest.main()
