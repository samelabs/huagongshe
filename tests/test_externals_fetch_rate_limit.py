"""externals-fetch 限流位置契约(0916 收口; G2.4C 迁 owner 到 services/cb).

修复的问题: 编排入口曾把 externals-fetch 限流放在 handler 入口, 于是所有
不发生同步上游外呼的路径(fresh DB / fresh negative / stale enqueue /
no_cas / 404)也消耗配额(登录 10/min、匿名全局 30/min), 并且 Redis 限流后端
故障时这些正常读取会被 fail-closed 打成 503。限流只应保护"即将执行
sync_fetch_and_store(...)"的分支。

契约(三点锁死):
  1) 不发生同步外呼的路径, 一次都不调用 enforce("externals-fetch", ...);
  2) absent 且即将同步外呼时, 恰好一次, 且在 sync_fetch_and_store 之前;
     额度不变: actor 10/min, anonymous-global 30/min;
  3) 限流失败(RateLimited/LimiterUnavailable)时 sync_fetch_and_store
     一次都不得执行。

G2.4C: 状态机下沉 services/cb.get_chemical_externals(actor_id), 限流用
G2.R neutral core enforce(非 enforce_http); HTTP/MCP adapter 只做映射。
"""

import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from api import routes
from api.core.rate_limit import LimiterUnavailable, RateLimited
from api.services import cb as cb_module
from api.services.cb import (
    ChemicalExternalsNotFoundError, get_chemical_externals,
)

ROW_EXISTS = (1, "7732-18-5")


class _Row:
    def __init__(self, value):
        self._value = value

    def fetchone(self):
        return self._value


class _Db:
    """最小 db 替身: 只回答编排的第一条 SELECT(id, cas)。"""

    def __init__(self, row):
        self._row = row
        self.commits = 0

    async def execute(self, *args, **kwargs):
        return _Row(self._row)

    async def commit(self):
        self.commits += 1


class ExternalsFetchRateLimitPlacementTests(unittest.IsolatedAsyncioTestCase):
    async def _call(self, *, actor_id=None, row=ROW_EXISTS, ensure_seq=(),
                    negative_fresh=False, sync_result=None, enforce_exc=None):
        """直调 shared orchestration; 返回 (结果或异常, 事件序列)。"""
        events: list[tuple] = []

        async def spy_enforce(bucket, identity, limit, window_seconds):
            events.append(("enforce", bucket, identity, limit, window_seconds))
            if enforce_exc is not None:
                raise enforce_exc

        seq = list(ensure_seq)
        counter = {"n": 0}

        async def fake_ensure(db, chemical_id, cas_number=None):
            idx = min(counter["n"], len(seq) - 1)
            counter["n"] += 1
            return dict(seq[idx])

        async def fake_negative(db, kind, cas_number=None):
            return negative_fresh

        async def fake_sync(db, chemical_id=None, cas_number=None):
            events.append(("sync", chemical_id))
            return dict(sync_result) if sync_result is not None else None

        async def fake_enqueue(db, **kwargs):
            reason = (kwargs.get("request_context") or {}).get("reason")
            events.append(("enqueue", reason))
            return 999

        db = _Db(row)
        with patch.object(cb_module, "enforce", spy_enforce), \
             patch.object(cb_module, "ensure_externals", fake_ensure), \
             patch.object(cb_module, "negative_is_fresh", fake_negative), \
             patch.object(cb_module, "sync_fetch_and_store", fake_sync), \
             patch.object(cb_module, "enqueue_cas_job", fake_enqueue):
            try:
                result = await get_chemical_externals(db, 1, actor_id=actor_id)
            except (ChemicalExternalsNotFoundError, RateLimited,
                    LimiterUnavailable) as exc:
                return exc, events
        return result, events

    @staticmethod
    def _enforce_calls(events):
        return [e for e in events if e[0] == "enforce"]

    # ---- 契约 1: 零外呼路径不吃配额 ----------------------------------

    async def test_fresh_db_read_never_touches_externals_fetch_budget(self):
        for actor_id in (None, 42):
            result, events = await self._call(
                actor_id=actor_id,
                ensure_seq=[{"state": "fresh", "entry": {"zh": "水"}, "suppliers": []}],
            )
            self.assertEqual(result["state"], "fresh")
            self.assertEqual(self._enforce_calls(events), [],
                             "fresh DB 读不得消耗 externals-fetch 配额")
            self.assertEqual([e for e in events if e[0] == "sync"], [],
                             "fresh DB 读不得同步外呼")

    async def test_zero_outbound_paths_never_touch_budget(self):
        # (a) fresh negative: 明确 not_found 在重问窗内 → 零外呼零入列
        result, events = await self._call(
            actor_id=None, ensure_seq=[{"state": "absent"}], negative_fresh=True)
        self.assertTrue(result.get("negative"))
        self.assertEqual(self._enforce_calls(events), [])
        self.assertEqual([e for e in events if e[0] in ("sync", "enqueue")], [])

        # (b) no_cas: 化合物无 CAS → 直接返回
        result, events = await self._call(
            actor_id=None, row=(1, None), ensure_seq=[{"state": "fresh"}])
        self.assertEqual(result["state"], "no_cas")
        self.assertEqual(self._enforce_calls(events), [])

        # (c) 404: 化合物不存在 → neutral 异常
        got, events = await self._call(actor_id=None, row=None,
                                       ensure_seq=[{"state": "fresh"}])
        self.assertIsInstance(got, ChemicalExternalsNotFoundError)
        self.assertEqual(str(got), "化合物不存在")
        self.assertEqual(self._enforce_calls(events), [])

        # (d) stale: 出旧数据 + 入列(worker 刷), 本身零同步外呼
        result, events = await self._call(
            actor_id=None,
            ensure_seq=[{"state": "stale", "entry": {"zh": "水"}, "suppliers": ["s"]}],
        )
        self.assertEqual(result["state"], "fresh")
        self.assertEqual(self._enforce_calls(events), [])
        self.assertEqual([e[0] for e in events], ["enqueue"], "stale 只入列不同步外呼")

    # ---- 契约 2: absent+即将外呼 → 恰好一次, 额度不变, 先限流后外呼 ----

    async def test_absent_sync_path_enforces_once_with_unchanged_budget(self):
        result, events = await self._call(
            actor_id=4711,
            ensure_seq=[{"state": "absent"},
                        {"state": "fresh", "entry": {"zh": "水"}, "suppliers": []}],
            sync_result={"status": "ok"},
        )
        self.assertEqual(self._enforce_calls(events),
                         [("enforce", "externals-fetch", "4711", 10, 60)],
                         "鉴权身份额度仍为 10/min")
        self.assertEqual([e[0] for e in events], ["enforce", "sync"],
                         "必须先限流、再同步外呼(单次)")
        self.assertEqual(result["state"], "fresh")

        result, events = await self._call(
            actor_id=None,
            ensure_seq=[{"state": "absent"},
                        {"state": "fresh", "entry": None, "suppliers": []}],
            sync_result={"status": "ok"},
        )
        self.assertEqual(self._enforce_calls(events),
                         [("enforce", "externals-fetch", "anonymous-global", 30, 60)],
                         "匿名额度仍为全局 30/min")
        self.assertEqual([e[0] for e in events], ["enforce", "sync"])

    async def test_sync_failed_enqueues_after_single_enforce(self):
        result, events = await self._call(
            actor_id=None, ensure_seq=[{"state": "absent"}],
            sync_result={"status": "error"})
        self.assertEqual([e[0] for e in events], ["enforce", "sync", "enqueue"])
        self.assertEqual(events[-1], ("enqueue", "sync_failed"))
        self.assertEqual(result["state"], "queued")

    async def test_sync_not_found_enforces_once_and_never_enqueues(self):
        result, events = await self._call(
            actor_id=None, ensure_seq=[{"state": "absent"}],
            sync_result={"status": "not_found"})
        self.assertEqual(len(self._enforce_calls(events)), 1)
        self.assertEqual([e[0] for e in events], ["enforce", "sync"])
        self.assertEqual(result["state"], "fresh")

    # ---- 契约 3: 限流失败不得外呼 -------------------------------------

    async def test_rate_limit_failure_blocks_sync_fetch_and_store(self):
        for exc in (
            LimiterUnavailable("限速服务暂时不可用，请稍后重试"),
            RateLimited("请求过于频繁，请稍后重试", retry_after=5),
        ):
            with self.subTest(exc=type(exc).__name__):
                got, events = await self._call(
                    actor_id=None, ensure_seq=[{"state": "absent"}], enforce_exc=exc)
                self.assertIsInstance(got, type(exc))
                self.assertEqual([e[0] for e in events], ["enforce"],
                                 "限流失败时不得执行 sync_fetch_and_store")


class AdapterMappingTests(unittest.IsolatedAsyncioTestCase):
    """§11/§12: adapter 只做映射; enforce/状态机不在 handler。"""

    def test_externals_http_route_removed(self):
        """E9-B 1.1: /externals 端点删除 — service 层限流契约测试保留。"""
        import api.routes as routes
        for route in routes.router.routes:
            path = getattr(route, "path", "")
            self.assertNotIn("/externals", path)
