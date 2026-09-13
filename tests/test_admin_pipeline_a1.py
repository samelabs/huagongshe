"""Admin A1 (0912): pipeline 健康语义 / 分区容错 / 缓存治理 / SSR 边界。

覆盖 PM 验收单第 9 节 10 条中的 1/2/3/4/5/6/7/8(9/10 是 SSR 边界, 以
layout 源码不变量 + 现有 /users/me 机制断言)。

规则来源(代码事实, 不发明阈值):
- workapi.py: last_seen 持久化被 redis 节流 EX=300 NX → 落库延迟最坏 ~360s
  → WORKER_STALE_S=300 / WORKER_OFFLINE_S=600
- lease 180s(worker_job_lease_seconds), CB 心跳 interval=max(20, 180//3)=60s

运行: . /tmp/hgs_test_env.sh && ./venv/bin/python -m unittest tests.test_admin_pipeline_a1
"""

from __future__ import annotations

import asyncio
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
LAYOUT = WEB / "app/(site)/samelabs/layout.tsx"
PANEL = WEB / "components/samelabs/PipelinePanel.tsx"

from api.services.pipeline_health import (  # noqa: E402
    RECENT_SUCCESS_S,
    WORKER_OFFLINE_S,
    WORKER_STALE_S,
    WorkerRuntime,
    build_worker_runtimes,
    chain_health,
    worker_runtime_status,
)

NOW = datetime(2026, 9, 12, 12, 0, 0, tzinfo=timezone.utc)


def _worker(worker_id="w1", *, enabled=True, scopes=("cas", "pubchem"),
            last_seen=None, runtime=None, age=None) -> WorkerRuntime:
    return WorkerRuntime(
        worker_id=worker_id, display_name=None, enabled=enabled,
        scopes=list(scopes), last_seen_at=last_seen,
        runtime=runtime or "online", last_seen_age_s=age,
    )


# ── 5/6/7: chain_health 判定矩阵 ──────────────────────────
class ChainHealthModelTests(unittest.TestCase):
    def _online_cas(self):
        return [_worker(last_seen=NOW - timedelta(seconds=30))]

    def test_queued_dead_worker_is_stalled(self):
        """验收5: queued + dead worker → stalled, 绝不 idle/healthy。"""
        h = chain_health(scope="cas", queued=100, leased=0, error=0,
                         latest_success_at=NOW - timedelta(seconds=7200),
                         gate_silent=False, metrics_available=True,
                         worker_runtimes=[], now=NOW)
        self.assertEqual("stalled", h["status"])
        self.assertFalse(h["has_recent_worker"])

    def test_queued_live_worker_is_backlogged(self):
        """验收6: queued + live worker → backlogged。"""
        h = chain_health(scope="cas", queued=100, leased=2, error=0,
                         latest_success_at=NOW - timedelta(seconds=60),
                         gate_silent=False, metrics_available=True,
                         worker_runtimes=self._online_cas(), now=NOW)
        self.assertEqual("backlogged", h["status"])
        self.assertTrue(h["has_recent_worker"])

    def test_no_queue_live_worker_idle_is_reasonable(self):
        """验收7: 无队列 + 在线 worker + 近期无写入 → idle(不冒充 healthy)。"""
        h = chain_health(scope="cas", queued=0, leased=0, error=0,
                         latest_success_at=NOW - timedelta(seconds=4 * 3600),
                         gate_silent=False, metrics_available=True,
                         worker_runtimes=self._online_cas(), now=NOW)
        self.assertEqual("idle", h["status"])

    def test_no_queue_recent_success_is_healthy(self):
        h = chain_health(scope="cas", queued=0, leased=0, error=0,
                         latest_success_at=NOW - timedelta(seconds=60),
                         gate_silent=False, metrics_available=True,
                         worker_runtimes=self._online_cas(), now=NOW)
        self.assertEqual("healthy", h["status"])
        self.assertTrue(h["recent_success"])

    def test_metrics_unavailable_never_masquerades_healthy(self):
        h = chain_health(scope="cas", queued=0, leased=0, error=0,
                         latest_success_at=NOW, gate_silent=False,
                         metrics_available=False,
                         worker_runtimes=self._online_cas(), now=NOW)
        self.assertEqual("unavailable", h["status"])

    def test_error_or_gate_silent_degrades(self):
        base = dict(scope="cas", queued=0, leased=0,
                    latest_success_at=NOW - timedelta(seconds=60),
                    metrics_available=True,
                    worker_runtimes=self._online_cas(), now=NOW)
        self.assertEqual("degraded", chain_health(error=5, gate_silent=False, **base)["status"])
        self.assertEqual("degraded", chain_health(error=0, gate_silent=True, **base)["status"])
        self.assertEqual("healthy", chain_health(error=0, gate_silent=False, **base)["status"])

    def test_degraded_wins_over_backlogged(self):
        """(0912 PM 修正) queued + worker + error → degraded, 不再是 backlogged。"""
        h = chain_health(scope="cas", queued=10, leased=0, error=5,
                         latest_success_at=NOW, gate_silent=False,
                         metrics_available=True,
                         worker_runtimes=self._online_cas(), now=NOW)
        self.assertEqual("degraded", h["status"])

    def test_gate_silent_degrades_idle(self):
        """(0912 PM 修正) idle + gate 静默 → degraded(空闲不掩盖闸门异常)。"""
        h = chain_health(scope="cas", queued=0, leased=0, error=0,
                         latest_success_at=NOW - timedelta(seconds=4 * 3600),
                         gate_silent=True, metrics_available=True,
                         worker_runtimes=self._online_cas(), now=NOW)
        self.assertEqual("degraded", h["status"])

    def test_backlogged_online_reason_is_factual(self):
        """事实语义: online worker 的 backlogged reason 不得声称"消化中"类行为。"""
        h = chain_health(scope="cas", queued=100, leased=2, error=0,
                         latest_success_at=NOW - timedelta(seconds=60),
                         gate_silent=False, metrics_available=True,
                         worker_runtimes=self._online_cas(), now=NOW)
        self.assertEqual("backlogged", h["status"])
        joined = "".join(h["reasons"])
        for banned in ("消化中", "正在处理", "正在消费", "正常处理"):
            self.assertNotIn(banned, joined)
        self.assertIn("在线 worker", joined)

    def test_backlogged_stale_only_reason_states_uncertain(self):
        """stale-only: backlogged + has_recent_worker=true, reason 必须说
        "近期心跳/状态待确认", 不得声称 online。"""
        stale = [_worker(last_seen=NOW - timedelta(seconds=400), runtime="stale",
                         age=400.0)]
        h = chain_health(scope="cas", queued=50, leased=0, error=0,
                         latest_success_at=NOW - timedelta(seconds=60),
                         gate_silent=False, metrics_available=True,
                         worker_runtimes=stale, now=NOW)
        self.assertEqual("backlogged", h["status"])
        self.assertTrue(h["has_recent_worker"])
        joined = "".join(h["reasons"])
        self.assertIn("近期心跳", joined)
        self.assertIn("状态待确认", joined)
        self.assertNotIn("在线 worker 覆盖", joined)

    def test_no_queue_recent_success_without_worker_is_idle_not_healthy(self):
        """无积压+近期有写入+无近期 worker → 不得 healthy, 保持 idle 如实说明。"""
        h = chain_health(scope="cas", queued=0, leased=0, error=0,
                         latest_success_at=NOW - timedelta(seconds=60),
                         gate_silent=False, metrics_available=True,
                         worker_runtimes=[], now=NOW)
        self.assertEqual("idle", h["status"])
        self.assertFalse(h["has_recent_worker"])
        self.assertTrue(h["recent_success"])
        self.assertIn("无近期 worker 心跳", "".join(h["reasons"]))

    def test_healthy_requires_recent_success_and_recent_worker(self):
        """healthy = recent_success AND has_recent_worker。"""
        h = chain_health(scope="cas", queued=0, leased=0, error=0,
                         latest_success_at=NOW - timedelta(seconds=60),
                         gate_silent=False, metrics_available=True,
                         worker_runtimes=self._online_cas(), now=NOW)
        self.assertEqual("healthy", h["status"])
        self.assertTrue(h["has_recent_worker"])
        self.assertTrue(h["recent_success"])

    def test_health_payload_has_no_has_online_worker(self):
        """payload 契约: 不再有 has_online_worker, 只有 has_recent_worker。"""
        h = chain_health(scope="cas", queued=0, leased=0, error=0,
                         latest_success_at=NOW, gate_silent=False,
                         metrics_available=True,
                         worker_runtimes=self._online_cas(), now=NOW)
        self.assertNotIn("has_online_worker", h)
        self.assertIn("has_recent_worker", h)

    def test_scope_coverage_matters(self):
        """只覆盖 pubchem 的在线 worker 救不了 cas 链。"""
        pb_only = [_worker(scopes=("pubchem",), last_seen=NOW - timedelta(seconds=30))]
        h = chain_health(scope="cas", queued=10, leased=0, error=0,
                         latest_success_at=None, gate_silent=False,
                         metrics_available=True, worker_runtimes=pb_only, now=NOW)
        self.assertEqual("stalled", h["status"])


# ── 8: worker runtime: enabled ≠ online ────────────────────
class WorkerRuntimeTests(unittest.TestCase):
    def test_enabled_but_stale_heartbeat(self):
        """验收8: enabled + 心跳 300~600s → stale(不标 online)。"""
        st, age = worker_runtime_status(
            True, NOW - timedelta(seconds=WORKER_STALE_S + 30), NOW)
        self.assertEqual("stale", st)
        self.assertGreater(age, WORKER_STALE_S)

    def test_enabled_but_offline_heartbeat(self):
        st, _ = worker_runtime_status(
            True, NOW - timedelta(seconds=WORKER_OFFLINE_S + 1), NOW)
        self.assertEqual("offline", st)

    def test_enabled_never_seen_is_offline_not_online(self):
        st, age = worker_runtime_status(True, None, NOW)
        self.assertEqual("offline", st)
        self.assertIsNone(age)

    def test_disabled_is_disabled_regardless_of_heartbeat(self):
        st, _ = worker_runtime_status(
            False, NOW - timedelta(seconds=5), NOW)
        self.assertEqual("disabled", st)

    def test_online_within_throttle_window(self):
        st, _ = worker_runtime_status(
            True, NOW - timedelta(seconds=WORKER_STALE_S - 1), NOW)
        self.assertEqual("online", st)

    def test_thresholds_derived_from_throttle_facts(self):
        """阈值必须仍与代码事实锚定: 300s 节流 / 600s 判死。"""
        self.assertEqual(300, WORKER_STALE_S)
        self.assertEqual(600, WORKER_OFFLINE_S)

    def test_build_worker_runtimes_projection(self):
        rows = [
            ("w-live", "live", True, ["cas", "pubchem"], NOW - timedelta(seconds=60)),
            ("w-dead", "dead", True, ["cas"], NOW - timedelta(seconds=3600)),
            ("w-off", None, False, ["pubchem"], None),
        ]
        out = build_worker_runtimes(rows, NOW)
        self.assertEqual(["online", "offline", "disabled"],
                         [w.runtime for w in out])
        self.assertEqual(["cas", "pubchem"], out[0].scopes)


# ── 2/3/4: 端点级: 分区容错 / last-known-good / 单飞 ────────
def _has_db():
    import os
    return bool(os.environ.get("TEST_DATABASE_URL"))


@unittest.skipUnless(_has_db(), "需要测试库")
class PipelineEndpointTests(unittest.TestCase):
    """optional section 注入失败 / 缓存降级, 用真端点函数验证。"""

    @classmethod
    def setUpClass(cls):
        import api.admin as admin_mod
        cls.admin_mod = admin_mod
        cls._reset()

    @classmethod
    def tearDownClass(cls):
        cls._reset()

    @classmethod
    def _reset(cls):
        # 锁属于事件循环: 用未绑定循环的原始状态替换(测试进程内无并发刷新者)
        cls.admin_mod._PIPELINE_STATS_CACHE.clear()
        cls.admin_mod._PIPELINE_STATS_LOCK = asyncio.Lock()

    def setUp(self):
        self._reset()

    def _admin(self):
        from api.core.security import Actor
        return Actor(id=1, username="a1-test", display_name="a1",
                     email="a1@test.local", role="admin", avatar_path=None,
                     auth_kind="session")

    def _payload(self):
        from tests.test_pipeline_contract import _engine
        from sqlalchemy.ext.asyncio import async_sessionmaker

        async def run():
            engine = _engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                    return await self.admin_mod.pipeline(actor=self._admin(), db=db)
            finally:
                await engine.dispose()
        return asyncio.run(run())

    def test_healthy_endpoint_shape(self):
        """端点整体形状: health/aging/stats/workers runtime 全到位。"""
        d = self._payload()
        for chain in ("cb", "pb"):
            self.assertIn("health", d[chain])
            self.assertIn("aging", d[chain])
            self.assertIn(d[chain]["health"]["status"],
                          ("healthy", "idle", "backlogged", "stalled",
                           "degraded", "unavailable"))
        self.assertIn("stats", d)
        for k in ("generated_at", "stale", "age_seconds"):
            self.assertIn(k, d["stats"])
        for w in d["workers"]:
            self.assertIn(w["runtime"], ("online", "stale", "offline", "disabled"))
            self.assertIn("scopes", w)
        # optional 三块都是 {available, error, value}
        for wrap in (d["supplier"], d["cb"]["seed"], d["cb"]["negative"]):
            self.assertEqual({"available", "error", "value"}, set(wrap))
        # aging 事实口径: 只有排队年龄; 租约年龄字段已删除(无 leased_at, 纯推测)
        for chain in ("cb", "pb"):
            self.assertEqual({"oldest_queued_age_s"}, set(d[chain]["aging"]))
            self.assertNotIn("has_online_worker", d[chain]["health"])

    def test_optional_failure_degrades_not_500(self):
        """验收2: optional stats 查询失败 → 仍 200, section available=False, 不冒充 0。"""
        import api.admin as admin_mod
        orig = admin_mod._scan_negative
        async def boom(db):
            raise RuntimeError("injected negative failure")
        admin_mod._scan_negative = boom
        try:
            d = self._payload()
        finally:
            admin_mod._scan_negative = orig
        self.assertFalse(d["cb"]["negative"]["available"])
        self.assertIn("injected negative failure", d["cb"]["negative"]["error"])
        self.assertIsNone(d["cb"]["negative"]["value"])
        # 其它块不受牵连
        self.assertTrue(d["supplier"]["available"])
        self.assertTrue(d["cb"]["seed"]["available"])

    def test_critical_failure_first_time_raises_no_fake_snapshot(self):
        """critical(critical 段)首次失败且无缓存 → 如实抛(不伪造)。"""
        import api.admin as admin_mod
        orig = admin_mod._scan_critical
        async def boom(db):
            raise RuntimeError("injected critical failure")
        admin_mod._scan_critical = boom
        try:
            with self.assertRaises(RuntimeError):
                self._payload()
        finally:
            admin_mod._scan_critical = orig

    def test_critical_failure_after_success_returns_stale_snapshot(self):
        """验收3: last-known-good —— 刷新失败继续返回旧 snapshot, 标 stale。"""
        import api.admin as admin_mod
        d1 = self._payload()   # 成功, 落缓存
        # 强制 TTL 过期
        snap = admin_mod._PIPELINE_STATS_CACHE["v"]
        admin_mod._PIPELINE_STATS_CACHE["v"] = {"v": snap["v"], "ts": snap["ts"] - 10_000}
        orig = admin_mod._scan_critical
        async def boom(db):
            raise RuntimeError("injected refresh failure")
        admin_mod._scan_critical = boom
        try:
            d2 = self._payload()
        finally:
            admin_mod._scan_critical = orig
        self.assertTrue(d2["stats"]["stale"])
        self.assertEqual(d1["stats"]["generated_at"], d2["stats"]["generated_at"])
        self.assertGreater(d2["stats"]["age_seconds"], 9000)
        # 数据仍在(不是 0 冒充)
        self.assertTrue(d2["supplier"]["available"])

    def test_cold_start_single_flight_no_crash_no_double_scan(self):
        """验收(0912 blocker2): 两个冷启动请求并发 → _scan_critical 只跑一次,
        两个请求都拿到结果, 无一因 cached=None 崩溃。"""
        import api.admin as admin_mod
        admin_mod._PIPELINE_STATS_CACHE.clear()
        calls = {"n": 0, "evt": asyncio.Event()}
        orig = admin_mod._scan_critical
        async def slow_scan(db):
            calls["n"] += 1
            await calls["evt"].wait()      # 挂住首次刷新, 直到第二请求到位
            return await orig(db)

        async def scenario():
            admin_mod._scan_critical = slow_scan
            try:
                engine, _ = admin_mod_engine()
                try:
                    async def hit():
                        async with sessionmaker(engine)() as db:
                            return await admin_mod.pipeline(actor=self._admin(), db=db)
                    # 请求A先起跑(进入慢刷新持锁), 让出后请求B再进入
                    tA = asyncio.create_task(hit())
                    await asyncio.sleep(0.3)   # A 已持锁在扫
                    tB = asyncio.create_task(hit())
                    await asyncio.sleep(0.3)   # B 已在锁上等待(冷启动不抢跑)
                    calls["evt"].set()         # 放行首次刷新
                    return await asyncio.gather(tA, tB)
                finally:
                    await engine.dispose()
            finally:
                admin_mod._scan_critical = orig

        ra, rb = asyncio.run(scenario())
        self.assertEqual(1, calls["n"], "冷启动并发必须只执行一次 _scan_critical")
        for r in (ra, rb):
            self.assertIn("stats", r)
            self.assertFalse(r["stats"]["stale"])
            self.assertTrue(r["supplier"]["available"])

    def test_cold_start_first_refresh_failure_raises(self):
        """(0912 blocker2) 首次刷新失败且无 snapshot → 明确抛错, 不造 0。"""
        import api.admin as admin_mod
        admin_mod._PIPELINE_STATS_CACHE.clear()
        orig = admin_mod._scan_critical
        async def boom(db):
            raise RuntimeError("cold start fail")
        admin_mod._scan_critical = boom
        try:
            with self.assertRaises(RuntimeError):
                self._payload()
        finally:
            admin_mod._scan_critical = orig

    def test_concurrent_refresh_single_flight(self):
        """验收4: 刷新锁占用时直接用旧 snapshot —— 不重复重扫。"""
        import api.admin as admin_mod
        d1 = self._payload()
        calls = {"n": 0}
        orig = admin_mod._scan_critical
        async def counting(db):
            calls["n"] += 1
            return await orig(db)
        admin_mod._scan_critical = counting
        admin_mod._PIPELINE_STATS_CACHE["v"] = {
            "v": admin_mod._PIPELINE_STATS_CACHE["v"]["v"],
            "ts": admin_mod._PIPELINE_STATS_CACHE["v"]["ts"] - 10_000,  # 过期
        }
        try:
            # 模拟"别的请求正在刷": 持锁状态下本请求必须直接降级用旧快照
            async def scenario():
                async with self.admin_mod._PIPELINE_STATS_LOCK:
                    engine, _ = admin_mod_engine()
                    try:
                        async with sessionmaker(engine)() as db:
                            return await self.admin_mod.pipeline(actor=self._admin(), db=db)
                    finally:
                        await engine.dispose()
            d2 = asyncio.run(scenario())
        finally:
            admin_mod._scan_critical = orig
        self.assertEqual(0, calls["n"], "锁占用期间不应触发重扫描")
        self.assertTrue(d2["stats"]["stale"])
        self.assertEqual(d1["stats"]["generated_at"], d2["stats"]["generated_at"])


def admin_mod_engine():
    from tests.test_pipeline_contract import _engine
    return _engine(), None


def sessionmaker(engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    return async_sessionmaker(engine, expire_on_commit=False)


# ── 9/10: SSR 管理边界(源码级不变量; 运行时行为靠 /users/me 机制) ──
class SamelabsAccessBoundaryTests(unittest.TestCase):
    """layout 必须在服务端完成: 未登录 redirect / 非 admin 不渲染 shell。"""

    def test_layout_gates_server_side(self):
        src = LAYOUT.read_text(encoding="utf-8")
        self.assertIn("redirect(", src, "未登录必须服务端 redirect")
        self.assertIn('"/login?next=/samelabs"', src)
        self.assertIn('user.role !== "admin"', src, "非 admin 分支必须存在")
        # 非 admin 分支(到 admin return 之前)不得渲染管理 shell 组件
        gate = src.split('user.role !== "admin"')[1]
        non_admin_block = gate.split("return <div")[1].split("</div>;")[0]
        self.assertNotIn("<SamelabsNav", non_admin_block,
                         "非 admin 分支不得渲染管理 shell")

    def test_layout_uses_existing_session_mechanism(self):
        src = LAYOUT.read_text(encoding="utf-8")
        self.assertIn("/users/me", src, "复用现有 /users/me, 不造第二套鉴权")

    def test_layout_keeps_noindex(self):
        src = LAYOUT.read_text(encoding="utf-8")
        self.assertIn("robots", src)
        self.assertIn("index: false", src)

    def test_panel_never_shows_admin_shell_content_to_members(self):
        """Pipeline 数据全部经 /admin/pipeline(服务端 admin 依赖 403),
        面板自身不再出现第二套权限文案分支之外的内幕内容降级渲染。"""
        src = PANEL.read_text(encoding="utf-8")
        # stale-while-refresh 状态机存在
        for phase in ("initial_loading", "ready", "refreshing", "stale"):
            self.assertIn(phase, src)
        # 首败完整 error / 有数据保留 + 重试
        self.assertIn("refreshFailed", src)
        self.assertIn("retryNow", src)
        # optional section 渲染"暂不可用"而非 0
        self.assertIn("sectionUnavailable", src)
        self.assertIn("暂不可用", src)

    def test_frontend_wording_is_factual(self):
        """前端事实文案契约: 禁止无吞吐证据的行为措辞与已删字段名。"""
        src = PANEL.read_text(encoding="utf-8")
        for banned in ("积压消化中", "worker 在线消化中", "最老租约",
                       "oldest_leased_age_s", "oldest_lease_expires_at",
                       "has_online_worker"):
            self.assertNotIn(banned, src, f"PipelinePanel 不得包含: {banned}")
        self.assertIn("has_recent_worker", src)
        self.assertIn("最老排队任务等待时间", src)
        self.assertIn("排队最久", src)

    def test_backend_pipeline_wording_is_factual(self):
        """后端事实文案契约: health 模型不得声称消费行为, admin 不得再算租约年龄。"""
        src = (ROOT / "api/services/pipeline_health.py").read_text(encoding="utf-8")
        self.assertNotIn("worker 在线消化中", src)
        self.assertNotIn("has_online_worker\": has_worker", src)
        api_src = (ROOT / "api/admin.py").read_text(encoding="utf-8")
        self.assertNotIn("oldest_leased_age_s", api_src)
        self.assertNotIn("oldest_lease_expires_at", api_src)

    def test_admin_dependency_exists_in_api(self):
        """API 侧: admin() 依赖仍是 role 检查(403), SSR 与 API 双层。"""
        src = (ROOT / "api/admin.py").read_text(encoding="utf-8")
        m = re.search(r"async def admin\(.*?\n(.*?)\n\n", src, re.S)
        self.assertIsNotNone(m)
        self.assertIn("403", m.group(0))
        self.assertIn('"admin"', m.group(0))


if __name__ == "__main__":
    unittest.main()
