"""P1 followup (0912): optional section 真实 SQL error 的降级隔离。

区分度要求(任务书): 不是"源码里存在 rollback"的字符串测试 —— 必须在
PostgreSQL 真实事务内制造 aborted transaction, 验证:
  1. supplier → available=false
  2. rollback 后 session 能继续执行 SQL
  3. 后续 optional section 正常 available
  4. generated_at 正常生成
  5. snapshot 整体成功进入 cache, 而非保留旧 LKG

运行: . /tmp/hgs_test_env.sh && /var/www/huagongshe/venv/bin/python -m unittest tests.test_admin_optional_section_rollback
"""

from __future__ import annotations

import asyncio
import os
import sys
import time as _t
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault(
    "HGS_DATABASE_URL",
    os.environ.get("TEST_DATABASE_URL",
                   "postgresql+asyncpg://test:test@127.0.0.1:5432/test_hgs"))
if os.environ["HGS_DATABASE_URL"].startswith("postgresql://"):
    os.environ["HGS_DATABASE_URL"] = "postgresql+asyncpg://" + \
        os.environ["HGS_DATABASE_URL"].split("://", 1)[1].split("?", 1)[0]

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

DB = os.environ["HGS_DATABASE_URL"]


def _engine():
    return create_async_engine(DB, poolclass=NullPool)


class OptionalSectionRollbackTests(unittest.TestCase):
    """在真实 PG 事务内: 第一个 optional section 抛 SQL error →
    后续 section 不得被 InFailedSQLTransactionError 污染。"""

    def setUp(self):
        import api.admin as admin_mod
        self.admin_mod = admin_mod
        admin_mod._PIPELINE_STATS_CACHE.clear()
        admin_mod._PIPELINE_STATS_BG.clear()

        # critical 打桩(非被测对象): 返回合法四元组, 不碰大表
        self._orig_critical = admin_mod._scan_critical

        async def fake_critical(db):
            return ([], 0, 0, 0)
        admin_mod._scan_critical = fake_critical

        # supplier 注入真实 SQL error: 除零在 PG 服务端 abort 事务
        self._orig_supplier = admin_mod._scan_supplier

        async def boom_supplier(db):
            await db.execute(text("SELECT 1/0"))
            raise AssertionError("PG 应当先抛服务端错误")
        admin_mod._scan_supplier = boom_supplier

    def tearDown(self):
        self.admin_mod._scan_critical = self._orig_critical
        self.admin_mod._scan_supplier = self._orig_supplier
        self.admin_mod._PIPELINE_STATS_CACHE.clear()
        self.admin_mod._PIPELINE_STATS_BG.clear()

    def test_aborted_tx_only_degrades_that_section(self):
        async def run():
            eng = _engine()
            try:
                async with async_sessionmaker(eng, expire_on_commit=False)() as db:
                    snap = await self.admin_mod._pipeline_refresh_stats(db)
                return snap
            finally:
                await eng.dispose()
        snap = asyncio.run(run())

        opt = snap["optional"]
        # 1: 出错 section 降级
        self.assertFalse(opt["supplier"]["available"])
        self.assertIn("division by zero", opt["supplier"]["error"])
        # 3+4: rollback 后 SQL 恢复 — 真实执行的 seed/negative 查询成功
        self.assertTrue(opt["seed"]["available"], "seed 不被 supplier 的事务污染")
        self.assertTrue(opt["negative"]["available"], "negative 不被污染")
        self.assertIsNotNone(opt["seed"]["value"])
        self.assertIsNotNone(opt["negative"]["value"])
        # 5: generated_at 正常生成(rollback 后 SELECT now() 成功)
        self.assertTrue(snap["generated_at"])

    def test_snapshot_enters_cache_not_lkg(self):
        """端到端: LKG 来自真实 endpoint 冷启动; 人为过期后再次冷启动,
        supplier 失败但 snapshot 整体成功进 cache(而非 refresh failed 留 LKG)。"""
        from api.core.security import Actor

        def actor():
            return Actor(id=1, username="rb", display_name="r", email="r@t.local",
                         role="admin", avatar_path=None, auth_kind="session")

        async def hit():
            eng = _engine()
            try:
                async with async_sessionmaker(eng, expire_on_commit=False)() as db:
                    return await self.admin_mod.pipeline(actor=actor(), db=db)
            finally:
                await eng.dispose()

        async def scenario():
            d1 = await hit()     # 冷启动 → snapshot 进 cache
            lkg = self.admin_mod._PIPELINE_STATS_CACHE["v"]["v"]
            self.assertFalse(lkg["optional"]["supplier"]["available"])  # 注入的错在
            self.assertTrue(lkg["optional"]["seed"]["available"])
            self.assertFalse(d1["stats"]["stale"])
            # 人为推过 TTL 再打: SWR — 本请求 stale 返回, 后台刷新换新
            self.admin_mod._PIPELINE_STATS_CACHE["v"]["ts"] = _t.monotonic() - 10_000
            d2 = await hit()
            self.assertTrue(d2["stats"]["stale"], "过期首请求应 stale 返回 LKG")
            self.assertIs(d2["stats"]["generated_at"], lkg["generated_at"])
            # 同一 loop 内等待后台刷新(独立 session)完成换新
            deadline = _t.monotonic() + 10
            while _t.monotonic() < deadline:
                cur = self.admin_mod._PIPELINE_STATS_CACHE["v"]["v"]
                if cur is not lkg:
                    break
                await asyncio.sleep(0.05)
            return lkg

        lkg = asyncio.run(scenario())
        cur = self.admin_mod._PIPELINE_STATS_CACHE["v"]["v"]
        # 6: 新 snapshot 整体成功进入 cache(supplier 单独降级)
        self.assertIsNot(cur, lkg)
        self.assertFalse(cur["optional"]["supplier"]["available"])
        self.assertTrue(cur["optional"]["seed"]["available"])
        self.assertTrue(cur["optional"]["negative"]["available"])
        self.assertTrue(cur["generated_at"])
        age = _t.monotonic() - self.admin_mod._PIPELINE_STATS_CACHE["v"]["ts"]
        self.assertLess(age, 60, "换新后应判定 fresh")


if __name__ == "__main__":
    unittest.main()
