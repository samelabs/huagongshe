"""搜索匿名副作用分支的行为契约（纯 mock，无 DB/Redis 依赖）。

两个副作用分支——库外 SMILES 建行（smiles-create）、库外 CAS 采集入队
（cas-search-fetch）——在匿名请求下按来源 IP 分桶做量化约束。本契约锁定
三种形态：
- 有来源 IP：落对应桶（30/min），超限时副作用被拒（不建行 / 不入队，
  搜索响应本身不受影响）；
- 缺来源 IP：不落任何限流桶（明确不落全站共享桶），副作用照常发生；
- 服务端渲染取数层转发 x-real-ip 后，SSR 流量应进入"有 IP"形态——
  该转发行为由 web/lib/api.server.ts 的单测锁定，此处锁定后端侧语义。
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from api.core.rate_limit import RateLimitError
from api.services import search as search_service


def _mock_db() -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar=lambda: 0))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _recorder(calls: list[tuple], *, raise_limited: bool = False):
    async def fake_enforce(bucket, identity, limit, window_seconds):
        calls.append((bucket, identity, limit, window_seconds))
        if raise_limited:
            raise RateLimitError("请求过于频繁，请稍后重试")

    return fake_enforce


class SmilesCreateGateTests(unittest.TestCase):
    """库外 SMILES 建行（smiles-create 桶）。"""

    def _run(self, client_ip, enforce_mock, resolve_mock, fetch_mock):
        with patch.object(search_service, "enforce", enforce_mock), \
             patch.object(search_service, "fetch_chemicals", fetch_mock), \
             patch.object(search_service, "reaction_lookup", new=AsyncMock(return_value=[])), \
             patch("api.services.reactions.resolve_or_create_chemical", resolve_mock):
            return asyncio.run(search_service.run_search_query(
                _mock_db(), "CCO", "exact", "CCO", 1, 30, 0,
                actor_id=None, client_ip=client_ip,
            ))

    def test_with_ip_buckets_by_ip_and_creates_row(self):
        calls: list[tuple] = []
        resolve = AsyncMock(return_value=(9101, True))
        # 首次=库内命中查询(miss)，其后=建行后回读
        fetch = AsyncMock(side_effect=[[], [{"id": 9101}]])
        chemicals, *_ = self._run("203.0.113.7", _recorder(calls), resolve, fetch)
        self.assertIn(("smiles-create", "ip:203.0.113.7", 30, 60), calls)
        resolve.assert_awaited_once()
        self.assertEqual(chemicals, [{"id": 9101}])

    def test_with_ip_rate_limited_degrades_to_empty_result(self):
        calls: list[tuple] = []
        resolve = AsyncMock(return_value=(9102, True))
        fetch = AsyncMock(side_effect=[[], [{"id": 9102}]])
        chemicals, *_ = self._run(
            "203.0.113.7", _recorder(calls, raise_limited=True), resolve, fetch)
        self.assertIn(("smiles-create", "ip:203.0.113.7", 30, 60), calls)
        resolve.assert_not_awaited()
        self.assertEqual(chemicals, [])

    def test_without_ip_skips_rate_limit_but_still_creates(self):
        calls: list[tuple] = []
        resolve = AsyncMock(return_value=(9103, True))
        fetch = AsyncMock(side_effect=[[], [{"id": 9103}]])
        chemicals, *_ = self._run(None, _recorder(calls), resolve, fetch)
        smiles_calls = [c for c in calls if c[0] == "smiles-create"]
        self.assertEqual(smiles_calls, [], "缺来源 IP 不得落任何限流桶（含全站共享桶）")
        resolve.assert_awaited_once()
        self.assertEqual(chemicals, [{"id": 9103}])


class CasSearchFetchGateTests(unittest.TestCase):
    """库外 CAS 采集入队（cas-search-fetch 桶）。"""

    def _run(self, client_ip, enforce_mock, state_mock, enqueue_mock):
        with patch("api.core.rate_limit.enforce", enforce_mock), \
             patch.object(search_service, "fetch_chemicals", AsyncMock(return_value=[])), \
             patch.object(search_service, "run_name_search", new=AsyncMock(return_value=([], False))), \
             patch.object(search_service, "reaction_lookup", new=AsyncMock(return_value=[])), \
             patch("api.services.cb.cas_search_state", state_mock), \
             patch("api.services.cb.enqueue_cas_search_fetch", enqueue_mock):
            return asyncio.run(search_service.run_search_query(
                _mock_db(), "7732-18-5", "exact", None, 1, 30, 0,
                actor_id=None, client_ip=client_ip,
            ))

    def test_with_ip_buckets_by_ip_and_enqueues(self):
        calls: list[tuple] = []
        state = AsyncMock(return_value="new")
        enqueue = AsyncMock(return_value=(True, "pending", None))
        chemicals, _, _, cas_fetch_pending, *_ = self._run(
            "203.0.113.8", _recorder(calls), state, enqueue)
        self.assertIn(("cas-search-fetch", "ip:203.0.113.8", 30, 60), calls)
        enqueue.assert_awaited_once()
        self.assertTrue(cas_fetch_pending)
        self.assertEqual(chemicals, [])

    def test_with_ip_rate_limited_skips_enqueue(self):
        calls: list[tuple] = []
        state = AsyncMock(return_value="new")
        enqueue = AsyncMock(return_value=(True, "pending", None))
        chemicals, _, _, cas_fetch_pending, *_ = self._run(
            "203.0.113.8", _recorder(calls, raise_limited=True), state, enqueue)
        self.assertIn(("cas-search-fetch", "ip:203.0.113.8", 30, 60), calls)
        state.assert_not_awaited()
        enqueue.assert_not_awaited()
        self.assertFalse(cas_fetch_pending)

    def test_without_ip_skips_rate_limit_but_still_enqueues(self):
        calls: list[tuple] = []
        state = AsyncMock(return_value="new")
        enqueue = AsyncMock(return_value=(True, "pending", None))
        chemicals, _, _, cas_fetch_pending, *_ = self._run(
            None, _recorder(calls), state, enqueue)
        cas_calls = [c for c in calls if c[0] == "cas-search-fetch"]
        self.assertEqual(cas_calls, [], "缺来源 IP 不得落任何限流桶（含全站共享桶）")
        enqueue.assert_awaited_once()
        self.assertTrue(cas_fetch_pending)


if __name__ == "__main__":
    unittest.main()
