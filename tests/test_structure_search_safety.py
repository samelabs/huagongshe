"""结构检索安全回归与并发闸门验收(0912 P0)。

覆盖三层:

1. **Substructure snapshot 不变量** — P0 复发形态是
   `mol @> ... ORDER BY c.id`(planner 换 pkey 顺序扫 1.24 亿行 → GiST 失效)。
   现设计: 无序 GiST + `LIMIT :cap` 取 snapshot(Redis 300s) + Python 排序 +
   分页切片 + 按 ID hydrate, SQL 里不再出现 OFFSET。
   CI 数据规模不足以驱动 planner, 故这里测 SQL 形态不变量。
   生产 EXPLAIN 证据: tests/fixtures/structure_search_explain_20260912.txt
   (修复前高选择性/深页 8s TIMEOUT; 修复后命中 chemicals_mol_gist_idx)。

2. **Similarity threshold / total 语义** — KNN GiST 不动; threshold 后过滤;
   total 只在 prefix 内已跌破 threshold 时给精确值, 否则 None。

3. **资源闸门** — fixed-window 限频 + in-flight 租约(actor 2 / global 4),
   租约原子获取、finally 释放、TTL 自愈, cache hit 不占闸门。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import time
import unittest

os.environ.setdefault("HGS_DATABASE_URL", os.environ.get("TEST_DATABASE_URL", ""))

# 确定性 fixture: 12 重原子(满足子结构 ≥10 下限), test DB 里按需创建/复用 —
# 测试不依赖任何本机 test DB 的具体 chemical id。
FIXTURE_SMILES = "CCOCCCOCCCO"

try:
    from tests.db_gate import test_db_or_skip  # noqa: E402

    _RAW_DB_URL = test_db_or_skip()
    DB_URL = "postgresql+asyncpg://" + _RAW_DB_URL.split("://", 1)[1]
    DB_URL = DB_URL.split("?", 1)[0]
except Exception:  # pragma: no cover - 无 test DB 时跳过 DB 用例
    DB_URL = None

from api.core import rate_limit
from api.core.cache import cache_delete, cache_get, cache_set, pool
from api.services import chemicals as chemicals_service
from api.services import search as search_service
import api.routes as routes


def _sql_blocks(source: str) -> list[str]:
    """只取真正的 SQL 块(含 SELECT), 跳过 docstring。"""
    return [block for block in re.findall(r'"""(.*?)"""', source, flags=re.S)
            if "SELECT" in block]


class SubstructureSqlInvariantTests(unittest.TestCase):
    """P0: 禁止任何 `mol @>` 查询块出现 ORDER BY id / SQL OFFSET。"""

    def setUp(self):
        self.snapshot_sql = "\n".join(_sql_blocks(inspect.getsource(
            chemicals_service.substructure_snapshot)))
        self.unified_src = inspect.getsource(search_service.run_search_query)
        self.unified_sub = next((b for b in _sql_blocks(self.unified_src) if "@>" in b), None)

    def test_snapshot_is_bounded_and_unordered(self):
        self.assertIn("LIMIT :cap", self.snapshot_sql)
        self.assertNotIn("ORDER BY", self.snapshot_sql,
                         "P0 复发: snapshot SQL 带排序 → planner 弃用 GiST")

    def test_snapshot_is_cached_with_ttl(self):
        src = inspect.getsource(chemicals_service.substructure_snapshot)
        self.assertIn("cache_get(key)", src)
        self.assertIn("cache_set(key, ids, ttl=SUBSTRUCTURE_SNAPSHOT_TTL)", src)
        self.assertEqual(chemicals_service.SUBSTRUCTURE_SNAPSHOT_TTL, 300)

    def test_snapshot_cap_is_250(self):
        """产品语义: 最多返回前 250 条子结构匹配(生产只读基准见报告)。"""
        self.assertEqual(chemicals_service.SUBSTRUCTURE_SNAPSHOT_CAP, 250)

    def test_unified_substructure_uses_snapshot(self):
        """统一搜索的 substructure 分支必须走同一 snapshot, 且全仓不再有
        `mol @> ... ORDER BY c.id` / SQL OFFSET 形态。"""
        self.assertIn("substructure_snapshot(db, canonical)", self.unified_src)
        self.assertIn("hydrate_chemicals(db, ids[offset:offset + page_size])", self.unified_src)
        self.assertIsNone(self.unified_sub, "unified 分支不应再自建 mol @> SQL")
        # 结构分支不得再出现自建排序/偏移(精确文本分支的文本搜索仍用它们, 故按分支切)
        structure_src = self.unified_src[self.unified_src.find('if mode == "substructure"'):]
        structure_src = structure_src[:structure_src.find("else:")]
        self.assertNotIn("@>", structure_src)
        self.assertNotIn("OFFSET", structure_src)
        self.assertNotIn("window = offset + page_size", structure_src.split("elif mode")[0])

    def test_hydrate_preserves_snapshot_order(self):
        src = inspect.getsource(chemicals_service.hydrate_chemicals)
        self.assertIn("items.sort(", src)
        self.assertNotIn("ORDER BY c.id", src)


class SimilaritySemanticsTests(unittest.TestCase):
    """KNN GiST 不动 + threshold 单一语义 + total 不冒充本页条数。"""

    def setUp(self):
        full = inspect.getsource(search_service.run_search_query)
        start = full.find('elif mode == "similarity"')
        end = full.find('else:', start)
        branch = full[start:end if end > -1 else len(full)]
        self.sim_sql = "\n".join(_sql_blocks(branch))
        self.sim_src = branch

    def test_knn_index_path_preserved(self):
        self.assertIn("ORDER BY c.morgan_bfp <%> morganbv_fp", self.sim_sql)
        self.assertNotIn("ORDER BY c.id", self.sim_sql)

    def test_threshold_post_filter(self):
        self.assertIn(">= threshold", self.sim_src)

    def test_total_semantics_are_explicit(self):
        self.assertIn("cut_inside", self.sim_src)
        # 0914 #1: qualifying 是无 OFFSET 的完整前缀, 精确 total 与页码无关
        self.assertIn("total = len(qualifying) if cut_inside else None", self.sim_src)

    def test_unified_search_accepts_threshold(self):
        sig = str(inspect.signature(search_service.run_search_query))
        self.assertRegex(sig, r"threshold: 'float' = 0\.7")

    def test_route_threshold_param_and_cache_key(self):
        src = inspect.getsource(routes.search)
        self.assertIn("threshold: float = Query(0.7", src)
        # G2.3 final: cache key 构造唯一 owner = shared orchestration
        orch = inspect.getsource(search_service.execute_search)
        self.assertIn("round(threshold, 3)", orch, "cache key 必须含 threshold")

    def test_route_no_fake_total(self):
        src = inspect.getsource(routes)
        self.assertNotIn('"total": len(items)', src, "本页条数冒充总数复发")

    def test_mcp_threshold_passthrough(self):
        with open("api/mcp_server.py") as handle:
            mcp = handle.read()
        self.assertIn("threshold: float = 0.7", mcp)
        self.assertIn("threshold=threshold", mcp)

    def test_frontend_no_hardcoded_70(self):
        with open("web/lib/i18n.ts") as handle:
            i18n = handle.read()
        self.assertNotIn("≥ 70%", i18n, "前端硬编码 70% 复发")


class GateWiringTests(unittest.TestCase):
    """闸门接线: cache-before-gate + 三层覆盖 + 无 MCP 旁路。"""

    def test_limits_are_documented_values(self):
        self.assertEqual(rate_limit.STRUCTURE_ACTOR_RATE_LIMIT, 6)
        self.assertEqual(rate_limit.STRUCTURE_GLOBAL_RATE_LIMIT, 30)
        self.assertEqual(rate_limit.STRUCTURE_ACTOR_INFLIGHT, 2)
        self.assertEqual(rate_limit.STRUCTURE_GLOBAL_INFLIGHT, 4)
        self.assertGreater(rate_limit.LEASE_TTL_SECONDS, 8)

    def test_global_inflight_leaves_connections(self):
        """4 个结构查询 ≤ 10 连接池的一半以下 — 至少 6 个留给普通请求。"""
        self.assertLessEqual(rate_limit.STRUCTURE_GLOBAL_INFLIGHT, 4)

    def test_all_structure_handlers_gated_after_cache(self):
        # G2.3 final: cache-before-gate 顺序唯一 owner = shared orchestration;
        # HTTP/MCP adapter 均经 execute_search 继承同一顺序。
        source = inspect.getsource(search_service.execute_search)
        cache_pos = source.find("await _cache_get(cache_key)")
        gate_pos = source.find("await _structure_enter(")
        self.assertGreater(cache_pos, -1, "orchestration 缺 cache 查询")
        self.assertGreater(gate_pos, cache_pos, "闸门必须在 cache miss 之后")
        self.assertIn("structure_exit", source, "orchestration 未释放租约")

    def test_mcp_has_no_bypass(self):
        """G2.3 后: MCP 直调 transport-neutral service, 但结构闸门/缓存口径
        与 HTTP 相同 —— 无 cache-before-gate 旁路, 也不经 HTTP handler。"""
        with open("api/mcp_server.py") as handle:
            mcp = handle.read()
        # 不得经 HTTP handler(G2.3 目标), 不得直连底层分页实现绕过闸门
        self.assertNotIn("routes_module.search(", mcp)
        self.assertNotIn("substructure_page(", mcp)
        self.assertNotIn("similarity_page(", mcp)
        # G2.3 final: MCP 直调 shared orchestration(execute_search)——
        # 闸门/缓存/cache-before-gate 顺序由 orchestration 唯一拥有,
        # MCP adapter 不再自带任何编排原语。
        start = mcp.index('@server.tool(name="search_chemistry_data"')
        block = mcp[start:mcp.index("@server.tool", start + 10)]
        self.assertIn("execute_search(", block, "MCP search 必须直调 shared orchestration")
        for banned in ("_cache_get", "_structure_enter", "_structure_exit",
                       "run_search_query", "v2:unified-search",
                       "canonicalize_smiles"):
            self.assertNotIn(banned, block, f"MCP search 不应再含 {banned}")

    def test_lease_is_atomic_and_ttl_bounded(self):
        src = inspect.getsource(rate_limit.acquire_lease)
        self.assertIn("eval(", src)
        self.assertIn("_ACQUIRE_LEASE", src)
        self.assertIn("PEXPIRE", rate_limit._ACQUIRE_LEASE)
        self.assertIn("INCR", rate_limit._ACQUIRE_LEASE)


async def _ensure_fixture_chemical(engine) -> tuple[int, bool]:
    """确保 test DB 里存在一个确定性的 fixture 化合物(有 smiles + mol + morgan_bfp)。

    返回 (chemical_id, created)。已存在则复用(不写库), 不存在则创建 —
    测试因此不依赖任何本机 test DB 的具体 id(similarity 需要 morgan_bfp,
    子结构需要 ≥10 重原子, FIXTURE_SMILES 同时满足)。
    """
    from sqlalchemy import text as sql_text

    async with engine.begin() as conn:
        row = (await conn.execute(sql_text(
            "SELECT id FROM chemistry.chemicals WHERE smiles=:s AND mol IS NOT NULL "
            "AND morgan_bfp IS NOT NULL ORDER BY id LIMIT 1"
        ), {"s": FIXTURE_SMILES})).fetchone()
        if row:
            return int(row[0]), False
        created = (await conn.execute(sql_text("""
            INSERT INTO chemistry.chemicals (smiles, mol, morgan_bfp)
            VALUES (:s, mol_from_smiles(:s), morganbv_fp(mol_from_smiles(:s)))
            RETURNING id
        """), {"s": FIXTURE_SMILES})).fetchone()
        return int(created[0]), True


async def _drop_fixture_chemical(engine, chemical_id: int) -> None:
    from sqlalchemy import text as sql_text

    async with engine.begin() as conn:
        await conn.execute(sql_text(
            "DELETE FROM chemistry.chemicals WHERE id=:id AND smiles=:s"
        ), {"id": chemical_id, "s": FIXTURE_SMILES})


def _build_test_app():
    """最小 ASGI app: 只挂 API router。

    刻意不挂 api.main.app — 它的 MCP streamable-http session manager 会起后台
    任务, 在 IsolatedAsyncioTestCase 的逐用例事件循环之间泄漏(Future attached
    to a different loop / Event loop is closed)。结构检索路由本身不需要 MCP。
    """
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.include_router(routes.router, prefix="/api")
    return test_app


class LoopLocalRedisMixin:
    """IsolatedAsyncioTestCase 每个用例独立事件循环; 共享的全局连接池里可能
    残留别的 loop 的连接 → "attached to a different loop"。本 mixin 在用例内
    换成本 loop 专用池(同时挂到 cache 与 rate_limit), 用完还原并断开。"""

    async def _bind_own_redis_pool(self):
        import os

        import redis.asyncio as redis

        from api.core import cache as cache_module

        self._own_pool = redis.ConnectionPool.from_url(
            os.environ["HGS_REDIS_URL"], decode_responses=True)
        self._pools = (cache_module, rate_limit)
        self._orig_pools = tuple(module.pool for module in self._pools)
        for module in self._pools:
            module.pool = self._own_pool

    async def _wipe_limits(self, bucket: str) -> None:
        """清掉本用例要用的 lease/rate 键 — 测试共用 Redis DB, 残留的
        fixed-window 计数会让后续用例拿到 429 而不是预期的 403/503。"""
        import redis.asyncio as redis

        client = redis.Redis(connection_pool=self._own_pool)
        for pattern in (f"lease:{bucket}:*", f"rate:{bucket}:*"):
            async for key in client.scan_iter(match=pattern):
                await client.delete(key)
        await client.aclose()

    async def _release_own_redis_pool(self):
        for module, original in zip(self._pools, self._orig_pools):
            module.pool = original
        await self._own_pool.disconnect()


class LeaseLayerTests(LoopLocalRedisMixin, unittest.IsolatedAsyncioTestCase):
    """in-flight 租约: 原子上限 / finally 释放 / TTL 自愈。"""

    BUCKET = "test-lease"

    async def asyncSetUp(self):
        await self._bind_own_redis_pool()
        await self._clear()

    async def asyncTearDown(self):
        await self._release_own_redis_pool()

    def _client(self):
        import redis.asyncio as redis

        return redis.Redis(connection_pool=self._own_pool)

    async def _clear(self):
        await self._wipe_limits(self.BUCKET)
        client = self._client()
        for identity in ("actor:1", "actor:2", "actor:3", "actor:4", "actor:5", "actor:9", "global"):
            await client.delete(f"lease:{self.BUCKET}:{identity}")

    async def _count(self, identity: str) -> int:
        return int(await self._client().get(f"lease:{self.BUCKET}:{identity}") or 0)

    async def test_actor_cap_is_atomic(self):
        grants = await asyncio.gather(*[
            rate_limit.acquire_lease(self.BUCKET, "actor:1", 2) for _ in range(10)
        ])
        self.assertEqual(sum(1 for value in grants if value), 2,
                         "并发下租约上限被击穿(非原子)")
        self.assertEqual(await self._count("actor:1"), 2)

    async def test_release_frees_slot(self):
        self.assertTrue(await rate_limit.acquire_lease(self.BUCKET, "actor:1", 1))
        self.assertFalse(await rate_limit.acquire_lease(self.BUCKET, "actor:1", 1))
        await rate_limit.release_lease(self.BUCKET, "actor:1")
        self.assertEqual(await self._count("actor:1"), 0)
        self.assertTrue(await rate_limit.acquire_lease(self.BUCKET, "actor:1", 1))

    async def test_stale_lease_recovers_by_ttl(self):
        """进程崩溃遗留的租约靠 TTL 自愈, 不需人工干预。"""
        self.assertTrue(await rate_limit.acquire_lease(self.BUCKET, "global", 1, ttl_seconds=1))
        self.assertFalse(await rate_limit.acquire_lease(self.BUCKET, "global", 1))
        await asyncio.sleep(1.2)
        self.assertTrue(await rate_limit.acquire_lease(self.BUCKET, "global", 1),
                        "stale 租约未随 TTL 释放")

    async def test_global_acquire_503_releases_actor_lease_immediately(self):
        """global 侧 acquire 抛 503(fail-closed)时, 已持有的 actor 租约必须当场
        释放, 不能等 TTL — 否则故障窗口内该 actor 的槽位被白锁 30s。"""
        from api.core.rate_limit import LimiterUnavailable

        original = rate_limit.acquire_lease

        async def flaky(bucket, identity, limit, ttl_seconds=rate_limit.LEASE_TTL_SECONDS):
            if identity == "global":
                raise LimiterUnavailable("结构检索限流服务暂时不可用，请稍后重试")
            return await original(bucket, identity, limit, ttl_seconds)

        rate_limit.acquire_lease = flaky
        try:
            with self.assertRaises(LimiterUnavailable) as ctx:
                await rate_limit.structure_enter(9, bucket=self.BUCKET)
        finally:
            rate_limit.acquire_lease = original
        self.assertEqual(await self._count("actor:9"), 0,
                         "global acquire 失败后 actor 租约未立即释放(要等 TTL)")

    async def test_enter_raises_429_when_full(self):
        """global 并发满(4)后, 新 actor 即使自身有空槽也必须 429。"""
        from api.core.rate_limit import ResourceBusy

        held = [await rate_limit.structure_enter(value, bucket=self.BUCKET) for value in (1, 2, 3, 4)]
        with self.assertRaises(ResourceBusy) as ctx:
            await rate_limit.structure_enter(5, bucket=self.BUCKET)
        self.assertEqual(ctx.exception.retry_after, 5)
        self.assertEqual(await self._count("actor:5"), 0, "被拒后 actor 槽位泄漏")
        for item in held:
            await rate_limit.structure_exit(item, bucket=self.BUCKET)

    async def test_failed_global_acquire_releases_actor_slot(self):
        """global 拿不到时必须回滚已持有的 actor 租约, 否则 actor 槽位泄漏。"""
        from api.core.rate_limit import ResourceBusy

        held = await rate_limit.structure_enter(1, bucket=self.BUCKET)
        await rate_limit.structure_enter(2, bucket=self.BUCKET)
        await rate_limit.structure_enter(3, bucket=self.BUCKET)   # 3/4 global
        await rate_limit.structure_enter(4, bucket=self.BUCKET)   # 4/4 global
        with self.assertRaises(ResourceBusy):
            await rate_limit.structure_enter(5, bucket=self.BUCKET)  # global 满
        self.assertEqual(await self._count("actor:5"), 0, "actor 租约泄漏")
        await rate_limit.structure_exit(held, bucket=self.BUCKET)


@unittest.skipUnless(DB_URL, "需要 test_hgs")
class SnapshotAndSimilarityDbTests(LoopLocalRedisMixin, unittest.IsolatedAsyncioTestCase):
    """真实 DB 行为: snapshot 分页稳定 / similarity total 边界。"""

    SMILES = FIXTURE_SMILES

    async def _pick_substructure_sample(self, session, need: int = 20) -> tuple[int, str]:
        """选一个 ≥10 重原子(产品下限)且 snapshot 至少 need 条的样本 —
        跨库稳健, 不写死 id。"""
        from rdkit import Chem

        from sqlalchemy import text as sql_text

        rows = (await session.execute(sql_text(
            "SELECT id, smiles FROM chemistry.chemicals "
            "WHERE mol IS NOT NULL AND smiles IS NOT NULL ORDER BY id"
        ))).fetchall()
        for value, smiles in rows:
            mol = Chem.MolFromSmiles(smiles)
            if mol is None or mol.GetNumHeavyAtoms() < 10:
                continue
            ids = await chemicals_service.substructure_snapshot(session, smiles)
            if len(ids) >= need:
                return int(value), smiles
        raise unittest.SkipTest("测试库缺少 ≥10 重原子且命中足够的样本")

    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        await self._bind_own_redis_pool()
        self.engine = create_async_engine(DB_URL)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.snapshot_keys = []
        self.fixture_id, self._fixture_created = await _ensure_fixture_chemical(self.engine)

    async def asyncTearDown(self):
        await cache_delete(*self.snapshot_keys)
        await cache_delete(f"v2:substructure:{self.fixture_id}:1:10",
                           f"v2:substructure:{self.fixture_id}:2:10",
                           f"v2:similarity:{self.fixture_id}:0.4:1:10",
                           f"v2:similarity:{self.fixture_id}:0.4:2:10")
        if self._fixture_created:
            await _drop_fixture_chemical(self.engine, self.fixture_id)
        await self.engine.dispose()
        await self._release_own_redis_pool()

    async def _snapshot(self):
        key = f"v3:substructure-snapshot:{chemicals_service.SUBSTRUCTURE_SNAPSHOT_CAP}:{self.SMILES}"
        self.snapshot_keys.append(key)
        await cache_delete(key)
        async with self.Session() as session:
            return await chemicals_service.substructure_snapshot(session, self.SMILES)

    async def test_snapshot_is_sorted_and_bounded(self):
        ids = await self._snapshot()
        self.assertLessEqual(len(ids), chemicals_service.SUBSTRUCTURE_SNAPSHOT_CAP)
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), len(set(ids)))

    async def test_snapshot_is_cached(self):
        key = f"v3:substructure-snapshot:{chemicals_service.SUBSTRUCTURE_SNAPSHOT_CAP}:{self.SMILES}"
        self.snapshot_keys.append(key)
        await cache_delete(key)
        async with self.Session() as session:
            first = await chemicals_service.substructure_snapshot(session, self.SMILES)
            second = await chemicals_service.substructure_snapshot(session, self.SMILES)
        self.assertEqual(first, second)
        self.assertEqual(await cache_get(key), first, "snapshot 未进缓存")



@unittest.skipUnless(DB_URL, "需要 test_hgs")
class ConcurrencyGateAcceptanceTests(LoopLocalRedisMixin, unittest.IsolatedAsyncioTestCase):
    """并发验收: 单 actor ≤2 / 多 actor global ≤4 / cache hit 不占槽 / 释放正确。"""

    APP_READY = False

    @classmethod
    def setUpClass(cls):
        try:
            import httpx  # noqa: F401

            cls.APP_READY = True
        except Exception:  # pragma: no cover
            cls.APP_READY = False

    async def asyncSetUp(self):
        if not self.APP_READY:
            self.skipTest("httpx/app 不可用")
        await self._bind_own_redis_pool()
        import httpx
        from api.core.security import Actor, public_or_actor

        self.Actor = Actor
        self.app = _build_test_app()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://test"
        )
        self.app.dependency_overrides[public_or_actor] = lambda: Actor(
            id=77, username="tester", display_name="tester", email="t@example.com",
            role="user", avatar_path=None, auth_kind="test",
        )
        # app 的 DB engine 是模块级共享的, 在别的 loop 里建过连接 → 本 loop 用
        # 自己的 engine(用完还原+dispose), 避免 "attached to a different loop"。
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from api.core import database as database_module

        self._database = database_module
        self._orig_engine = database_module.engine
        self._orig_session = database_module.async_session
        self.app_engine = create_async_engine(DB_URL)
        self._original_session_factory = database_module.async_session
        database_module.engine = self.app_engine
        database_module.async_session = async_sessionmaker(self.app_engine, expire_on_commit=False)
        self.fixture_id, self._fixture_created = await _ensure_fixture_chemical(self.app_engine)

        self._patched = search_service.run_search_query
        self._rate = (rate_limit.STRUCTURE_ACTOR_RATE_LIMIT,
                      rate_limit.STRUCTURE_GLOBAL_RATE_LIMIT)
        # 本组只验并发层: 把 fixed-window 抬高, 免得两层混在一起
        rate_limit.STRUCTURE_ACTOR_RATE_LIMIT = 10_000
        rate_limit.STRUCTURE_GLOBAL_RATE_LIMIT = 10_000
        # 0915: 真实 SMILES(直链烷烃, 10-49 个重原子) — 必须过生产
        # canonicalize_smiles(无效合成串如 C9100001CO 会 400, 测试根本到不了
        # 闸门层)。run_search_query 整体 mock, 生产 validation/gate 不放松。
        self._queries = ["C" * (10 + i) for i in range(40)]
        self._cache_keys = [f"v2:unified-search:substructure:0.7:1:30:{value}"
                            for value in self._queries]
        await cache_delete(*self._cache_keys)

    async def asyncTearDown(self):
        search_service.run_search_query = self._patched
        rate_limit.STRUCTURE_ACTOR_RATE_LIMIT, rate_limit.STRUCTURE_GLOBAL_RATE_LIMIT = self._rate
        self.app.dependency_overrides.clear()
        await cache_delete(*self._cache_keys)
        await cache_delete(f"v2:substructure:{self.fixture_id}:1:30")
        await self.client.aclose()
        if self._fixture_created:
            await _drop_fixture_chemical(self.app_engine, self.fixture_id)
        # 恢复共享 engine/factory 后再 dispose 本 loop 的 engine — 不碰全局实现。
        self._database.engine = self._orig_engine
        self._database.async_session = self._orig_session
        await self.app_engine.dispose()
        # 清理本用例占用的租约键 — 必须在还原本 loop 池之前做, 否则会落到
        # 共享池(绑定别的 loop)上, 报 "attached to a different loop"。
        import redis.asyncio as redis

        own_client = redis.Redis(connection_pool=self._own_pool)
        for identity in ("global", "actor:77"):
            await own_client.delete(f"lease:structure-search:{identity}")
        await own_client.aclose()
        await self._release_own_redis_pool()

    def _slow(self, tracker: dict, delay: float = 0.4):
        async def slow(db, query, mode, canonical, page, page_size, offset, **kw):
            tracker["live"] += 1
            tracker["max"] = max(tracker["max"], tracker["live"])
            try:
                await asyncio.sleep(delay)
                # 8 元组契约(0915): capped 末位 — 化学品/total/反应/pending/
                # canonical/cas_hit/has_more/capped
                return [], 3, [], False, canonical, None, False, False
            finally:
                tracker["live"] -= 1
        return slow

    async def test_single_actor_concurrency_capped_at_2(self):
        tracker = {"live": 0, "max": 0}
        search_service.run_search_query = self._slow(tracker)
        results = await asyncio.gather(*[
            self.client.get(f"/api/search?q={value}&mode=substructure")
            for value in self._queries[:10]
        ])
        codes = sorted(response.status_code for response in results)
        self.assertLessEqual(tracker["max"], 2, "单 actor 并发进 DB 超过 2")
        self.assertEqual(codes.count(200), 2)
        self.assertEqual(codes.count(429), 8, f"多余请求应为 429, 实际 {codes}")
        self.assertNotIn(503, codes)
        self.assertNotIn(500, codes)

    async def test_multi_actor_global_cap_4(self):
        tracker = {"live": 0, "max": 0}
        search_service.run_search_query = self._slow(tracker)

        from api.core.security import Actor, public_or_actor

        # 5 个 actor 同时各发 4 个请求(共 20): actor 层各 2, global 层合计 4
        def make_override(actor_id):
            def override():
                return Actor(id=actor_id, username=f"u{actor_id}", display_name="u",
                             email="u@example.com", role="user", avatar_path=None,
                             auth_kind="test")
            return override

        async def fire(actor_id: int, values: list):
            self.app.dependency_overrides[public_or_actor] = make_override(actor_id)
            return await asyncio.gather(*[
                self.client.get(f"/api/search?q={value}&mode=substructure") for value in values
            ])

        batches = await asyncio.gather(*[
            fire(actor_id, self._queries[(actor_id - 1) * 4:actor_id * 4])
            for actor_id in (1, 2, 3, 4, 5)
        ])
        responses = [response for group in batches for response in group]
        codes = [response.status_code for response in responses]
        self.assertLessEqual(tracker["max"], 4, "跨 actor 并发进 DB 超过 global 4")
        self.assertTrue(all(code in (200, 429) for code in codes), codes)
        self.assertGreaterEqual(codes.count(429), 1, "global 上限未生效")

    async def test_cache_hit_does_not_take_slot(self):
        tracker = {"live": 0, "max": 0}
        search_service.run_search_query = self._slow(tracker)
        payload = {"page": 1, "page_size": 30, "total": 0, "chemicals": []}
        for value in self._queries[:6]:
            await cache_set(f"v2:unified-search:substructure:0.7:1:30:{value}", payload, ttl=60)
        results = await asyncio.gather(*[
            self.client.get(f"/api/search?q={value}&mode=substructure") for value in self._queries[:6]
        ])
        self.assertEqual([response.status_code for response in results], [200] * 6)
        self.assertEqual(tracker["max"], 0, "cache hit 仍进了 DB/占了并发槽")

    async def test_failure_releases_slot(self):
        async def boom(db, query, mode, canonical, page, page_size, offset, **kw):
            raise RuntimeError("simulated failure")

        search_service.run_search_query = boom
        response = await self.client.get(f"/api/search?q={self._queries[0]}&mode=substructure")
        self.assertEqual(response.status_code, 503)
        import redis.asyncio as redis

        client = redis.Redis(connection_pool=self._own_pool)
        self.assertEqual(int(await client.get("lease:structure-search:global") or 0), 0,
                         "异常路径未释放 global 租约")
        self.assertEqual(int(await client.get("lease:structure-search:actor:77") or 0), 0,
                         "异常路径未释放 actor 租约")

    async def test_ordinary_request_not_starved(self):
        """结构查询压满时, 普通化合物详请仍能拿到连接并快速返回。"""
        tracker = {"live": 0, "max": 0}
        search_service.run_search_query = self._slow(tracker, delay=0.6)
        heavy = asyncio.gather(*[
            self.client.get(f"/api/search?q={value}&mode=substructure") for value in self._queries[:10]
        ])
        await asyncio.sleep(0.15)  # 让结构查询先占住槽位
        started = time.monotonic()
        ordinary = await self.client.get(f"/api/chemicals/{self.fixture_id}")
        elapsed = time.monotonic() - started
        self.assertEqual(ordinary.status_code, 200)
        self.assertLess(elapsed, 3.0, f"普通请求被结构检索拖慢: {elapsed:.2f}s")
        await heavy


class SnapshotPaginationEndTests(unittest.TestCase):
    """snapshot 分页尾部语义: 到尾部必须收敛, 且绝不把 cap 冒充真实匹配总数。"""

    CAP = chemicals_service.SUBSTRUCTURE_SNAPSHOT_CAP

    def test_uncapped_snapshot_total_is_exact_everywhere(self):
        ids = list(range(1, 41))          # 40 < 250 = 完整匹配集
        for page in (1, 2, 3, 4):
            offset = (page - 1) * 10
            self.assertEqual(chemicals_service._snapshot_total(ids, offset, 10), 40)

    def test_capped_snapshot_mid_pages_keep_more_results(self):
        ids = list(range(1, self.CAP + 1))
        for page in (1, 2):
            offset = (page - 1) * 10
            self.assertIsNone(chemicals_service._snapshot_total(ids, offset, 10),
                              "上限内仍有更多 → 应显示更多结果")

    def test_capped_snapshot_last_page_converges(self):
        ids = list(range(1, self.CAP + 1))
        last_page = self.CAP // 10                     # page 25, offset 240
        offset = (last_page - 1) * 10
        total = chemicals_service._snapshot_total(ids, offset, 10)
        self.assertEqual(total, self.CAP,
                         "snapshot 最后一页必须给出确定结果数, 不能继续显示更多结果")
        beyond = offset + 10                            # 越过 snapshot 尾部
        self.assertEqual(chemicals_service._snapshot_total(ids, beyond, 10), self.CAP)



class LeaseFailClosedTests(LoopLocalRedisMixin, unittest.IsolatedAsyncioTestCase):
    """0912: 结构检索 lease fail-closed — Redis 故障时 503, 绝不放进 DB。"""

    BUCKET = "test-fail-closed"

    async def asyncSetUp(self):
        await self._bind_own_redis_pool()
        await self._wipe_limits(self.BUCKET)
        await self._wipe_limits("structure-search")

    async def asyncTearDown(self):
        await self._release_own_redis_pool()

    def _broken_pool(self):
        import redis.asyncio as redis

        return redis.ConnectionPool.from_url(
            "redis://127.0.0.1:6399/15", socket_connect_timeout=0.2, socket_timeout=0.2)

    async def test_acquire_lease_503_on_redis_failure(self):
        from api.core.rate_limit import LimiterUnavailable

        broken = self._broken_pool()
        original = rate_limit.pool
        rate_limit.pool = broken
        try:
            with self.assertRaises(LimiterUnavailable) as ctx:
                await rate_limit.acquire_lease(self.BUCKET, "global", 4)
        finally:
            rate_limit.pool = original
            await broken.disconnect()

    async def test_structure_enter_fails_closed(self):
        from api.core.rate_limit import LimiterUnavailable

        broken = self._broken_pool()
        original = rate_limit.pool
        rate_limit.pool = broken
        try:
            with self.assertRaises(LimiterUnavailable) as ctx:
                await rate_limit.structure_enter(1, bucket=self.BUCKET)
        finally:
            rate_limit.pool = original
            await broken.disconnect()

    async def test_release_tolerates_redis_failure(self):
        broken = self._broken_pool()
        original = rate_limit.pool
        rate_limit.pool = broken
        try:
            await rate_limit.release_lease(self.BUCKET, "global")   # 不得抛
        finally:
            rate_limit.pool = original
            await broken.disconnect()

    async def test_route_returns_503_and_never_calls_service(self):
        """端到端: Redis 故障 → 503, 且结构查询函数一次都没被调用。"""
        import httpx
        from api.core import database as database_module
        from api.core.security import Actor, public_or_actor

        calls = []

        async def spy(db, query, mode, canonical, page, page_size, offset, **kw):
            calls.append(query)
            return [], 0, [], False, canonical, None, False

        original_service = search_service.run_search_query
        search_service.run_search_query = spy
        test_app = fastapi_app = _build_test_app()
        test_app.dependency_overrides[public_or_actor] = lambda: Actor(
            id=88, username="fc", display_name="fc", email="fc@example.com",
            role="user", avatar_path=None, auth_kind="test")
        broken = self._broken_pool()
        original_pool = rate_limit.pool
        rate_limit.pool = broken
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=fastapi_app), base_url="http://test"
            ) as client:
                response = await client.get("/api/search?q=CCO&mode=substructure")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(calls, [], "Redis 故障时仍进入了结构查询")
        finally:
            rate_limit.pool = original_pool
            await broken.disconnect()
            search_service.run_search_query = original_service
            fastapi_app.dependency_overrides.clear()
            await database_module.engine.dispose()


if __name__ == "__main__":
    unittest.main()
