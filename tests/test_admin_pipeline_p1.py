"""P1 (0912): stale-while-revalidate 契约 — pipeline / governance 双侧。

规则来源(任务书):
- 已有 snapshot 后, 任何用户请求都不得因 TTL 过期同步等待昂贵统计刷新
- 只有冷启动(无任何 snapshot)允许等待一次(single-flight)
- 后台 refresh 用独立 DB session(请求 session 生命周期结束后仍安全)
- refresh 成功原子替换; 失败保留 last-known-good(继续 stale)
- 同时 N 个 stale 请求只触发 1 次 refresh(集合门+锁双保险)
- task 异常必须被消费(无 "Task exception was never retrieved")

并发测试纪律: 每个 task 独立 AsyncSession(AsyncSession 禁并发 execute),
不改变生产 session 设计。

运行: . /tmp/hgs_test_env.sh && /var/www/huagongshe/venv/bin/python -m unittest tests.test_admin_pipeline_p1
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time as _t
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# HGS_DATABASE_URL 必须指向 asyncpg 驱动的测试库(import api.admin 时
# create_async_engine 拒绝 psycopg2)。与 tests/test_cb_negative.py 同模式。
os.environ.setdefault(
    "HGS_DATABASE_URL",
    os.environ.get("TEST_DATABASE_URL",
                   "postgresql+asyncpg://test:test@127.0.0.1:5432/test_hgs"))
if os.environ["HGS_DATABASE_URL"].startswith("postgresql://"):
    os.environ["HGS_DATABASE_URL"] = "postgresql+asyncpg://" + \
        os.environ["HGS_DATABASE_URL"].split("://", 1)[1].split("?", 1)[0]

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

DB = os.environ["HGS_DATABASE_URL"]


def _engine():
    return create_async_engine(DB, poolclass=NullPool)


def _actor():
    from api.core.security import Actor
    return Actor(id=1, username="p1", display_name="p", email="p@t.local",
                 role="admin", avatar_path=None, auth_kind="session")


class StaleWhileRevalidateTests(unittest.TestCase):
    def setUp(self):
        import api.admin as admin_mod
        import api.services.pipeline_governance as gov_mod
        self.admin_mod = admin_mod
        self.gov_mod = gov_mod
        admin_mod._PIPELINE_STATS_CACHE.clear()
        admin_mod._PIPELINE_STATS_BG.clear()
        gov_mod._GOV_CACHE.clear()
        gov_mod._GOV_BG.clear()
        # refresh 打桩: 计数 + 可控延迟/失败(不碰真实大表扫描)。
        # release 用 bool + sleep 轮询: asyncio.Event 绑定首次 await 的 loop,
        # 测试里多次 asyncio.run 各建新 loop 会 "attached to a different loop"。
        self.calls = {"pipeline": 0, "gov": 0}
        self.release = {"pipeline": False, "gov": False}
        self.fail = {"pipeline": False, "gov": False}
        self._orig = (admin_mod._pipeline_refresh_stats,
                      gov_mod.governance_snapshot)

        _OPT = {k: {"available": True, "error": None, "value": None}
                for k in ("supplier", "seed", "negative")}

        async def _gate(which: str):
            while not self.release[which]:
                await asyncio.sleep(0.02)

        async def pipe_refresh(db):
            self.calls["pipeline"] += 1
            await _gate("pipeline")
            if self.fail["pipeline"]:
                raise RuntimeError("injected pipeline refresh failure")
            return {"critical": ([], 0, 0, 0), "optional": dict(_OPT),
                    "generated_at": "fresh"}

        async def gov_snapshot(db):
            self.calls["gov"] += 1
            await _gate("gov")
            if self.fail["gov"]:
                raise RuntimeError("injected gov refresh failure")
            return {"sections": {"tick": self.calls["gov"]}}

        admin_mod._pipeline_refresh_stats = pipe_refresh
        gov_mod.governance_snapshot = gov_snapshot

    def tearDown(self):
        self.admin_mod._pipeline_refresh_stats, self.gov_mod.governance_snapshot = self._orig
        self.admin_mod._PIPELINE_STATS_CACHE.clear()
        self.admin_mod._PIPELINE_STATS_BG.clear()
        self.gov_mod._GOV_CACHE.clear()
        self.gov_mod._GOV_BG.clear()

    # ── helper: 每次请求独立 engine+session(同一事件循环内 await 完) ──
    def _hit_pipeline(self, *, timeout=5.0):
        async def run():
            eng = _engine()
            try:
                async with async_sessionmaker(eng, expire_on_commit=False)() as db:
                    return await asyncio.wait_for(
                        self.admin_mod.pipeline(actor=_actor(), db=db), timeout)
            finally:
                await eng.dispose()
        return asyncio.run(run())

    def _hit_gov(self, *, timeout=5.0):
        async def run():
            eng = _engine()
            try:
                async with async_sessionmaker(eng, expire_on_commit=False)() as db:
                    return await asyncio.wait_for(
                        self.gov_mod.get_governance(db), timeout)
            finally:
                await eng.dispose()
        return asyncio.run(run())

    def _seed(self, mod, cache_name, *, ttl_back=10_000):
        opt = {k: {"available": True, "error": None, "value": None}
               for k in ("supplier", "seed", "negative")}
        getattr(mod, cache_name)["v"] = {
            "v": {"critical": ([], 0, 0, 0), "optional": opt,
                  "generated_at": "seed"},
            "ts": _t.monotonic() - ttl_back}

    def _seed_gov(self, *, ttl_back=10_000):
        self.gov_mod._GOV_CACHE["v"] = {
            "v": {"sections": {"tick": 0}}, "ts": _t.monotonic() - ttl_back}

    # 1: stale + 无 refresh 在跑 → 立即返回, 不等待 scanner
    def test_stale_returns_immediately_without_waiting(self):
        self._seed(self.admin_mod, "_PIPELINE_STATS_CACHE")
        # release 未 set → 任何同步等待都会 5s 超时; 立即返回则通过
        d = self._hit_pipeline(timeout=5.0)
        self.assertTrue(d["stats"]["stale"])
        self.assertEqual(d["stats"]["generated_at"], "seed")
        self.assertGreaterEqual(self.calls["pipeline"], 1, "应已 spawn 后台刷新")
        # 消化后台任务(避免跨测试泄漏)
        asyncio.run(self._drain(self.admin_mod._PIPELINE_STATS_BG))

    @staticmethod
    async def _drain(tasks: set):
        for t in list(tasks):
            try:
                await t
            except Exception:
                pass

    def test_gov_stale_returns_immediately_without_waiting(self):
        self._seed_gov()
        d = self._hit_gov(timeout=5.0)
        self.assertTrue(d["stale"])
        self.assertGreaterEqual(self.calls["gov"], 1)
        asyncio.run(self._drain(self.gov_mod._GOV_BG))

    # 2: N 个 stale 请求并发 → 只 1 次 refresh(每 task 独立 session)
    def test_concurrent_stale_single_refresh(self):
        self._seed(self.admin_mod, "_PIPELINE_STATS_CACHE")

        async def one_request():
            eng = _engine()
            try:
                async with async_sessionmaker(eng, expire_on_commit=False)() as db:
                    return await asyncio.wait_for(
                        self.admin_mod.pipeline(actor=_actor(), db=db), 5)
            finally:
                await eng.dispose()

        async def scenario():
            tasks = [asyncio.create_task(one_request()) for _ in range(5)]
            results = await asyncio.wait_for(asyncio.gather(*tasks), 5)
            # 后台刷新挂起(release 未放行)期间检查: 只 spawn 了 1 个任务
            in_flight = len(self.admin_mod._PIPELINE_STATS_BG)
            self.release["pipeline"] = True
            await self._drain(self.admin_mod._PIPELINE_STATS_BG)
            return results, in_flight

        results, in_flight = asyncio.run(scenario())
        self.assertEqual(len(results), 5)
        for r in results:
            self.assertTrue(r["stats"]["stale"], "并发 stale 全部立即返回旧值")
            self.assertEqual(r["stats"]["generated_at"], "seed")
        self.assertEqual(1, in_flight, "在飞后台任务必须恰好 1 个")
        self.assertEqual(1, self.calls["pipeline"],
                         "N 个 stale 并发只允许 1 次昂贵 refresh")

    # 3: 后台 refresh 失败 → 旧 snapshot 保留并继续 stale
    def test_background_refresh_failure_keeps_last_known_good(self):
        self._seed(self.admin_mod, "_PIPELINE_STATS_CACHE")
        self.fail["pipeline"] = True
        self.release["pipeline"] = True
        with self.assertLogs("api.admin", level="ERROR") as logs:
            d1 = self._hit_pipeline()      # stale 返回 + 后台失败(被记录)
            asyncio.run(self._drain(self.admin_mod._PIPELINE_STATS_BG))
        self.assertTrue(d1["stats"]["stale"])
        self.assertEqual(d1["stats"]["generated_at"], "seed")
        self.assertTrue(any("background refresh failed" in m for m in logs.output),
                        "后台失败必须留痕")
        # 再打一次: 缓存仍是旧 snapshot(未被失败清空/覆盖)
        d2 = self._hit_pipeline()
        self.assertEqual(d2["stats"]["generated_at"], "seed")
        self.assertEqual("seed",
                         self.admin_mod._PIPELINE_STATS_CACHE["v"]["v"]["generated_at"])
        asyncio.run(self._drain(self.admin_mod._PIPELINE_STATS_BG))

    # 4: refresh 成功 → 下一请求读新 snapshot
    def test_successful_refresh_replaces_snapshot(self):
        self._seed(self.admin_mod, "_PIPELINE_STATS_CACHE")
        self.release["pipeline"] = True
        d1 = self._hit_pipeline()
        self.assertTrue(d1["stats"]["stale"])
        self.assertEqual(d1["stats"]["generated_at"], "seed")
        deadline = _t.monotonic() + 5
        while (self.admin_mod._PIPELINE_STATS_CACHE["v"]["v"]["generated_at"] == "seed"
               and _t.monotonic() < deadline):
            asyncio.run(asyncio.sleep(0.05))
        self.assertEqual(
            "fresh", self.admin_mod._PIPELINE_STATS_CACHE["v"]["v"]["generated_at"],
            "后台刷新成功后 cache 必须原子换新")
        d2 = self._hit_pipeline()
        self.assertEqual(d2["stats"]["generated_at"], "fresh")
        self.assertFalse(d2["stats"]["stale"])

    # 5: 冷启动 single-flight — N 请求只扫一次(同步等待路径)
    def test_cold_start_single_flight_scans_once(self):
        async def one_request():
            eng = _engine()
            try:
                async with async_sessionmaker(eng, expire_on_commit=False)() as db:
                    return await self.admin_mod.pipeline(actor=_actor(), db=db)
            finally:
                await eng.dispose()

        async def scenario():
            tA = asyncio.create_task(one_request())
            await asyncio.sleep(0.3)     # A 已持锁在扫(release 未放行)
            tB = asyncio.create_task(one_request())
            await asyncio.sleep(0.3)     # B 在锁上等待
            self.release["pipeline"] = True
            return await asyncio.gather(tA, tB)

        ra, rb = asyncio.run(scenario())
        self.assertEqual(1, self.calls["pipeline"], "冷启动并发只允许一次扫描")
        self.assertFalse(ra["stats"]["stale"])
        self.assertFalse(rb["stats"]["stale"])

    # 6: request DB session 结束后后台 refresh 仍安全 —
    #    源码不变量: 后台路径用独立 async_session(), 请求 db 不进 task。
    def test_bg_refresh_uses_independent_session_source(self):
        src = (ROOT / "api" / "admin.py").read_text(encoding="utf-8")
        self.assertIn("async with async_session() as db", src)
        self.assertNotIn("_pipeline_stats_spawn_refresh(db)", src)
        gsrc = (ROOT / "api" / "services" / "pipeline_governance.py").read_text(encoding="utf-8")
        self.assertIn("async with async_session() as db", gsrc)
        self.assertNotIn("_gov_spawn_refresh(db)", gsrc)
        # 后台任务异常被消费: _reap 调 t.exception()
        self.assertIn("_ = t.exception()", src)
        self.assertIn("_ = t.exception()", gsrc)

    # 7: 双侧同语义 — governance stale 也不等待, 成功后换新
    def test_pipeline_and_governance_share_semantics(self):
        self._seed_gov()
        self.release["gov"] = True
        d1 = self._hit_gov()
        self.assertTrue(d1["stale"])
        deadline = _t.monotonic() + 5
        while (not self.gov_mod._GOV_CACHE["v"]["v"].get("sections")
               and _t.monotonic() < deadline):
            asyncio.run(asyncio.sleep(0.05))
        d2 = self._hit_gov()
        self.assertFalse(d2["stale"], "governance 后台刷新成功后不得再标 stale")

    # 8: 集合门自身 — BG 非空时 spawn 直接 no-op(不靠锁排队)
    def test_spawn_gate_blocks_duplicate_tasks(self):
        async def scenario():
            # 预置一个挂起中的后台任务
            hold = asyncio.Event()
            async def hang():
                await hold.wait()
            t = asyncio.get_running_loop().create_task(hang())
            self.admin_mod._PIPELINE_STATS_BG.add(t)
            try:
                before = len(self.admin_mod._PIPELINE_STATS_BG)
                self.admin_mod._pipeline_stats_spawn_refresh()
                after = len(self.admin_mod._PIPELINE_STATS_BG)
                return before, after
            finally:
                hold.set()
                await t
                self.admin_mod._PIPELINE_STATS_BG.discard(t)
        before, after = asyncio.run(scenario())
        self.assertEqual((1, 1), (before, after), "集合非空时不得再建后台任务")


if __name__ == "__main__":
    unittest.main()
