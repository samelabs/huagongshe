"""P0 (admin-data-p0) governance 修复验收测试 (0912)。

覆盖任务书 3 项:

3A 事务隔离 —— section 报错后必须 rollback, 否则 PostgreSQL 事务进入 aborted 态,
   后续每个 section 连锁 InFailedSQLTransactionError。
   本测试用真实 PG 错误(SELECT 1/0)触发中断(不是源码字符串断言):
   * 注入 section unavailable 且 error 含 division by zero
   * 其后所有真实 section 的可用性与"无注入对照组"完全一致(真实 SQL 跑通)
   * snapshot 整体成功返回; 同一 session 在 snapshot 之后仍能执行真实 SQL

3B name_index_distribution —— 禁止再对 9.28M 行 name_index 全表 GROUP BY。
   * available=True / mode='sample'; value={exact,sample_size,matched,ratio,groups}
   * groups 元素 {kind,lang,source,matched}(样本计数, 不冒充全库 count)
   * 在 statement_timeout=8000ms(生产同款)下完成且 < 8s

3C generated_at —— 必须是 snapshot 生成时刻, 不是请求时刻; fresh/stale 都返回
   该 snapshot 时间, stale 不得伪装成刚生成。

运行: . /tmp/hgs_test_env.sh && ./venv/bin/python -m unittest tests.test_admin_governance_p0
"""

from __future__ import annotations

import asyncio
import os
import time
import unittest
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

DB = os.environ.get("TEST_DATABASE_URL", "").replace(
    "postgresql://", "postgresql+asyncpg://").split("?")[0]


async def _snapshot_with(db, inject: dict | None = None):
    """跑一次 governance_snapshot; inject 的 section 插在最前(其后全为真实 section)。"""
    import api.services.pipeline_governance as g
    orig = dict(g._SECTIONS)
    if inject:
        g._SECTIONS = {**inject, **orig}
    try:
        return await g.governance_snapshot(db), list(orig)
    finally:
        g._SECTIONS = orig


class P0GovBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DB:
            raise unittest.SkipTest("需要 TEST_DATABASE_URL")

    def tearDown(self):
        import api.services.pipeline_governance as g
        g._GOV_CACHE.clear()


class TransactionIsolationTests(P0GovBase):
    """3A: 真实 PostgreSQL 事务中断 → 后续 section 仍用真实 SQL 成功。"""

    def test_section_abort_is_isolated_and_rolled_back(self):
        probe_calls: list[str] = []

        async def boom(db):
            probe_calls.append("boom")
            await db.execute(text("SELECT 1/0"))  # 真实 PG 错误 → 事务 aborted

        async def run():
            eng = create_async_engine(DB)
            try:
                async with async_sessionmaker(eng, expire_on_commit=False)() as db:
                    await db.execute(text("SET statement_timeout = '30000ms'"))
                    # 对照组: 不注入, 记录每个 section 的真实可用性
                    control, names = await _snapshot_with(db)
                    # 实验组: 第一个 section 把事务打断
                    snap, _ = await _snapshot_with(db, {"txn_abort_probe": boom})
                    # rollback 生效的最强证据: 同一 session 之后还能跑真实 SQL
                    after = (await db.execute(text("SELECT 1"))).scalar()
                    sampled = (await db.execute(text(
                        "SELECT count(*) FROM chemistry.name_index "
                        "TABLESAMPLE SYSTEM_ROWS(50)"))).scalar()
                    return control, names, snap, after, sampled
            finally:
                await eng.dispose()

        control, names, snap, after, sampled = asyncio.run(run())

        self.assertEqual(["boom"], probe_calls)
        # 本 section unavailable, 且是真实 PG 错误
        probe = snap["txn_abort_probe"]
        self.assertFalse(probe["available"])
        self.assertIn("division by zero", probe["error"])
        self.assertEqual("error", probe["mode"])
        # snapshot 整体成功 + 每个真实 section 与对照组一致(被中断拖垮时这里会全 False)
        self.assertTrue(names)
        for name in names:
            self.assertEqual(control[name]["available"], snap[name]["available"],
                             f"{name}: 对照组={control[name]['error']!r} "
                             f"实验组={snap[name]['error']!r}")
        # 关键的"后续真实 SQL"section 必须真的跑通
        for name in ("name_index_distribution", "canonical_name_coverage",
                     "cb_name_index_missing"):
            self.assertTrue(snap[name]["available"], f"{name}: {snap[name]['error']}")
        # 同一 session 后续可用(没有 rollback 时这里会 InFailedSQLTransactionError)
        self.assertEqual(1, after)
        self.assertGreaterEqual(int(sampled), 0)

    def test_no_injection_keeps_transaction_clean(self):
        """对照组健全性: 无注入时 snapshot 后 session 立即可用。"""

        async def run():
            eng = create_async_engine(DB)
            try:
                async with async_sessionmaker(eng, expire_on_commit=False)() as db:
                    await db.execute(text("SET statement_timeout = '30000ms'"))
                    snap, names = await _snapshot_with(db)
                    after = (await db.execute(text("SELECT 1"))).scalar()
                    return snap, names, after
            finally:
                await eng.dispose()

        snap, names, after = asyncio.run(run())
        self.assertEqual(1, after)
        self.assertNotIn("txn_abort_probe", snap)
        self.assertTrue(all(snap[n]["available"] for n in ("name_index_distribution",)))


class DistributionSampleTests(P0GovBase):
    """3B: 分布改样本契约, 且在生产 statement_timeout 下不再超时。"""

    def test_distribution_is_sample_not_full_table(self):
        async def run():
            from api.services.pipeline_governance import name_index_distribution
            eng = create_async_engine(DB)
            try:
                async with async_sessionmaker(eng, expire_on_commit=False)() as db:
                    # 生产同款限制: 全表 GROUP BY(旧实现) 在这里必然 QueryCanceled
                    await db.execute(text("SET statement_timeout = '8000ms'"))
                    t0 = time.monotonic()
                    sec = await name_index_distribution(db)
                    return sec, time.monotonic() - t0
            finally:
                await eng.dispose()

        sec, elapsed = asyncio.run(run())
        self.assertTrue(sec["available"], sec["error"])
        self.assertEqual("sample", sec["mode"])
        v = sec["value"]
        self.assertFalse(v["exact"])
        self.assertIsInstance(v["sample_size"], int)
        # test_hgs 的 name_index 可能为空 → 只断言「契约 + 时限」, 不要求必须有行;
        # 生产库有行的实跑证据: /tmp/p0_probe.json (groups 5 条 / matched 3000)。
        for g in v["groups"]:
            self.assertEqual({"kind", "lang", "source", "matched"}, set(g))
            self.assertNotIn("count", g)  # 旧全库 count 契约必须消失
            self.assertGreater(g["matched"], 0)
        self.assertEqual(v["matched"], sum(g["matched"] for g in v["groups"]))
        # 样本量级: 远小于 9.28M 行(没有全表聚合)
        self.assertLessEqual(v["matched"], v["sample_size"])
        self.assertLess(elapsed, 8.0, f"样本查询 {elapsed:.2f}s ≥ 生产 statement_timeout")


class GeneratedAtTests(P0GovBase):
    """3C: generated_at = snapshot 生成时刻; stale 不得伪装成刚生成。"""

    def test_generated_at_is_snapshot_time_not_request_time(self):
        import api.services.pipeline_governance as g

        sentinel = "2026-01-01T00:00:00+0800"

        async def run():
            eng = create_async_engine(DB)
            try:
                async with async_sessionmaker(eng, expire_on_commit=False)() as db:
                    await db.execute(text("SET statement_timeout = '30000ms'"))
                    g._GOV_CACHE.clear()
                    r1 = await g.get_governance(db)          # 冷启动: 真扫一次
                    # fresh 响应的 generated_at 必须来自 cache 内那次 snapshot 的时刻
                    cached_ts = g._GOV_CACHE["v"]["generated_at"]
                    # 篡改 cache 内的 snapshot 时刻 → 只有"返回 snapshot 时刻"的实现
                    # 才会把 sentinel 透出; 返回"请求时刻"的实现必然透出当前时间。
                    g._GOV_CACHE["v"]["generated_at"] = sentinel
                    g._GOV_CACHE["v"]["ts"] = time.monotonic() - (g._GOV_TTL + 60)
                    await g._GOV_LOCK.acquire()              # 挡后台刷新, 保持 stale 态
                    try:
                        r2 = await g.get_governance(db)
                    finally:
                        g._GOV_LOCK.release()
                    return r1, r2, cached_ts
            finally:
                await eng.dispose()

        r1, r2, cached_ts = asyncio.run(run())

        # fresh: 就是刚才那次 snapshot 的时刻(与现在同秒级), 且等于 cache 内时间戳
        self.assertFalse(r1["stale"])
        self.assertEqual(cached_ts, r1["generated_at"])
        stamp = datetime.strptime(r1["generated_at"], "%Y-%m-%dT%H:%M:%S%z")
        self.assertLess(abs((datetime.now(timezone.utc) - stamp).total_seconds()), 120)
        # stale: 返回 cache 里的 snapshot 时刻(sentinel), 而不是请求时刻
        self.assertTrue(r2["stale"])
        self.assertEqual(sentinel, r2["generated_at"])
        # stale 不得伪装成刚生成: 透出的时刻就是旧 snapshot 的时刻(远早于现在)
        old = datetime.strptime(r2["generated_at"], "%Y-%m-%dT%H:%M:%S%z")
        age = (datetime.now(timezone.utc) - old).total_seconds()
        self.assertGreater(age, 3600, f"stale 响应透出了近似当前的时刻(diff={age:.0f}s)")


if __name__ == "__main__":
    unittest.main()
