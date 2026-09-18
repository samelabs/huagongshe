"""E7 §7/§8 — chemical detail enrich 契约冻结: core == full(兼容别名)。

锁:
1. 归一只在入口一次(services.chemicals.normalize_enrich, HTTP/MCP 共用);
2. 两个 adapter 都把归一后的规范值交给同一 application flow
   (services.chemicals.get_chemical_detail) —— 不存在第二业务路径;
3. 同一输入下 core 与 full 返回体完全一致(真链 DB, HTTP 与 MCP 两侧);
4. service 只接受规范值: 任何未归一的分叉在此暴露, 不静默生效。

契约口径: core = canonical current behavior; full = core 的兼容别名,
不代表额外 enrichment(无第二来源/无额外查询/无额外字段)。
"""
from __future__ import annotations

import asyncio
import inspect
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.services.chemicals import (  # noqa: E402
    ENRICH_CANONICAL,
    ENRICH_COMPAT_ALIASES,
    normalize_enrich,
)
from tests.db_gate import test_db_or_skip  # noqa: E402


def _dsn(url: str) -> str:
    base = url.split("?")[0]
    if base.startswith("postgresql://"):
        base = "postgresql+asyncpg://" + base.split("://", 1)[1]
    return base


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, default=str)


async def _stub_enqueue(db, cid, *, priority, allow_refresh, actor=None):
    """enrichment 入队桩: 固定 (result, job_id, needs_commit) → 两侧确定性一致。"""
    return {"status": "stub"}, None, False


class FakeCtx:
    """MCP Context 桩: 只暴露 headers(get_chemical 不解析 actor)。"""

    def __init__(self, headers: dict | None = None):
        self.headers = dict(headers or {})


class _SessionCtx:
    def __init__(self, engine):
        self._engine = engine
        self._session = None

    async def __aenter__(self):
        from sqlalchemy.ext.asyncio import AsyncSession
        self._session = AsyncSession(self._engine)
        return self._session

    async def __aexit__(self, *exc):
        await self._session.close()
        return False


class NormalizeEnrichTests(unittest.TestCase):
    """归一入口本身的行为(唯一映射点)。"""

    def test_core_is_canonical(self):
        self.assertEqual(normalize_enrich("core"), ENRICH_CANONICAL)

    def test_compat_alias_maps_to_core(self):
        self.assertEqual(tuple(ENRICH_COMPAT_ALIASES), ("full",))
        for alias in ENRICH_COMPAT_ALIASES:
            self.assertEqual(normalize_enrich(alias), ENRICH_CANONICAL)

    def test_default_missing_value_is_core(self):
        self.assertEqual(normalize_enrich(None), ENRICH_CANONICAL)
        self.assertEqual(normalize_enrich(""), ENRICH_CANONICAL)

    def test_unknown_value_is_not_silently_rewritten(self):
        # 未知值不归一到 core: 拒绝责任在 HTTP schema / MCP ToolError
        self.assertEqual(normalize_enrich("bogus"), "bogus")

    def test_service_rejects_non_canonical_enrich(self):
        from api.services.chemicals import get_chemical_detail
        with self.assertRaises(ValueError):
            asyncio.run(get_chemical_detail(
                object(), 1, actor_id=None, priority=50, enrich="bogus"))

    def test_service_holds_no_enrich_branch(self):
        """orchestration 不按 enrich 分支(唯一实现路径)。"""
        from api.services.chemicals import get_chemical_detail
        source = inspect.getsource(get_chemical_detail)
        self.assertNotIn("if enrich", source)


class AdapterNormalizationTests(unittest.TestCase):
    """两个 adapter 都把归一值交给同一 flow, 不复制业务路径。"""

    def test_http_adapter_normalizes_before_flow(self):
        from api import routes as routes_module

        fake = AsyncMock(return_value={"id": 1, "details": {}, "enrichment": {}})
        with patch.object(routes_module, "get_chemical_detail", fake):
            for sent in ("core", "full"):
                fake.reset_mock()
                asyncio.run(routes_module.chemical_detail(
                    chemical_id=1, enrich=sent, display=False,
                    actor=None, db=object()))
                self.assertEqual(fake.await_args.kwargs["enrich"], ENRICH_CANONICAL,
                                 f"HTTP enrich={sent} 未归一到规范值")

    def test_mcp_tool_normalizes_before_flow(self):
        from api import mcp_server as mcp_mod
        from api.services import chemicals as chem_svc

        fake = AsyncMock(return_value={"id": 1, "details": {}, "enrichment": {}})
        with patch.object(chem_svc, "get_chemical_detail", fake):
            for sent in ("core", "full"):
                fake.reset_mock()
                asyncio.run(mcp_mod.build_mcp_server().call_tool(
                    "get_chemical", {"chemical_id": 1, "enrich": sent},
                    context=FakeCtx()))
                self.assertEqual(fake.await_args.kwargs["enrich"], ENRICH_CANONICAL,
                                 f"MCP enrich={sent} 未归一到规范值")

    def test_externals_endpoint_has_no_enrich_selector(self):
        """externals 语义与 enrich 无关(不受别名影响, 也无第二路径)。"""
        from api import routes as routes_module
        self.assertNotIn("enrich", inspect.signature(
            routes_module.chemical_externals).parameters)


class CoreFullEquivalenceTests(unittest.TestCase):
    """真链 DB: 同一输入下 core 与 full 返回体完全一致。"""

    def test_http_core_full_identical_payload(self):
        url = test_db_or_skip()
        asyncio.run(self._http_equivalence(url))

    async def _http_equivalence(self, url: str) -> None:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.pool import NullPool

        from api import routes as routes_module
        from api.services import enrichment as enrich_svc

        engine = create_async_engine(_dsn(url), poolclass=NullPool)
        try:
            async with AsyncSession(engine) as session:
                cid = (await session.execute(text(
                    "SELECT id FROM chemistry.chemicals ORDER BY id LIMIT 1"))).scalar()
                self.assertIsNotNone(cid, "test DB 无 chemicals 行")
                out: dict[str, dict] = {}
                for sent in ("core", "full"):
                    with patch.object(enrich_svc, "enqueue_chemical_if_needed",
                                      _stub_enqueue):
                        out[sent] = await routes_module.chemical_detail(
                            chemical_id=int(cid), enrich=sent, display=False,
                            actor=None, db=session)
        finally:
            await engine.dispose()

        self.assertEqual(set(out["core"]), set(out["full"]), "response shape 不一致")
        self.assertEqual(out["core"]["id"], out["full"]["id"], "identity 字段不一致")
        self.assertEqual(_canonical(out["core"]), _canonical(out["full"]),
                         "core 与 full 返回体不一致")

    def test_mcp_core_full_identical_payload(self):
        url = test_db_or_skip()
        asyncio.run(self._mcp_equivalence(url))

    async def _mcp_equivalence(self, url: str) -> None:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.pool import NullPool

        from api import mcp_server as mcp_mod
        from api.services import enrichment as enrich_svc

        engine = create_async_engine(_dsn(url), poolclass=NullPool)
        try:
            async with AsyncSession(engine) as session:
                cid = (await session.execute(text(
                    "SELECT id FROM chemistry.chemicals ORDER BY id LIMIT 1"))).scalar()
            self.assertIsNotNone(cid, "test DB 无 chemicals 行")
            out: dict[str, dict] = {}
            with patch.object(mcp_mod, "async_session",
                              lambda: _SessionCtx(engine)), \
                    patch.object(enrich_svc, "enqueue_chemical_if_needed",
                                 _stub_enqueue):
                for sent in ("core", "full"):
                    res = await mcp_mod.build_mcp_server().call_tool(
                        "get_chemical", {"chemical_id": int(cid), "enrich": sent},
                        context=FakeCtx())
                    out[sent] = getattr(res, "structuredContent", None) or \
                        getattr(res, "content", None)
        finally:
            await engine.dispose()

        self.assertIsNotNone(out["core"], "MCP 未返回结构化结果")
        self.assertEqual(_canonical(out["core"]), _canonical(out["full"]),
                         "MCP core 与 full 返回体不一致")


if __name__ == "__main__":
    unittest.main()
