"""E9-B Chemical detail 合流契约测试。

覆盖任务卡 §1/§7:
- core: canonical 正常返回; PB/CB service 调用计数 = 0; enqueue = 0; 无 commit
- full: PB+CB / PB-only / CB-only / 双无 / PB fail / CB fail / 冲突事实保两条证据
- surface: /details 404、/externals 404、MCP 无 get_chemical_externals、
  MCP get_chemical core/full 真有差异
- 状态: no_cas/negative/absent → none; 单源失败 → unavailable + 不 500
"""
from __future__ import annotations

import asyncio
import inspect
import unittest
from unittest.mock import AsyncMock, patch

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.db_gate import test_db_or_skip  # noqa: E402

CANONICAL_ROW = [1, 962, "CCO", None, "water", None, None, "H2O", 18.02, 18.02,
                 "IKTEST", None, ["7732-18-5"], [], [], [], [], [], None]


class _Row:
    """SQLAlchemy 风格行(fetch_chemicals 返回元素, 索引访问)。"""

    def __init__(self, values):
        self._values = values

    def __getitem__(self, i):
        return self._values[i]


class _Recorder:
    def __init__(self):
        self.calls: dict[str, int] = {}

    def bump(self, key):
        self.calls[key] = self.calls.get(key, 0) + 1


class _Result:
    """SQLAlchemy result 桩: 覆盖 orchestration 真实消费的接口链
    (mappings/fetchone/first/fetchall/scalar/scalars)。"""

    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def mappings(self):
        return self

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def scalar(self):
        return self._scalar if self._scalar is not None else (
            self._rows[0][0] if self._rows else None)

    def scalars(self):
        return self

    def __iter__(self):
        return iter(self._rows)


def _make_db(rec: _Recorder | None = None, cas="7732-18-5"):
    db = AsyncMock()

    async def execute_side_effect(*a, **k):
        if rec is not None:
            rec.bump("db_execute")
        return _Result(rows=[_Row([cas])])

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.commit = AsyncMock(side_effect=(lambda: rec.bump("commit")) if rec else None)
    db.rollback = AsyncMock()
    return db


def _chemical_dict(values):
    """与 services.chemicals.chemical_dict 同构的 dict(索引→命名 key)。"""
    return {
        "id": values[0], "pubchem_cid": values[1], "smiles": values[2],
        "pubchem_smiles": values[3], "preferred_name": values[4],
        "iupac_name": values[5], "name_cn": None, "molecular_formula": values[6],
        "average_mass": values[7], "monoisotopic_mass": values[8],
        "inchikey": values[9], "dtxsid": values[10], "cas_numbers": values[11] or [],
        "nikkaji_numbers": values[12] or [], "chembl_ids": values[13] or [],
        "ec_numbers": values[14] or [], "unii_codes": values[15] or [],
        "chebi_ids": values[16] or [], "similarity": None,
    }


CANONICAL_VALUES = [1, 962, "CCO", None, "water", None, "H2O", 18.02, 18.02,
                    "IKTEST", None, ["7732-18-5"], [], [], [], [], []]


async def _fake_fetch(values=None):
    values = values if values is not None else CANONICAL_VALUES
    async def fetch(db, sql, params):
        return [_chemical_dict(values)]
    return fetch


async def _fake_context():
    async def context(db, result, cid, uid):
        result.update({"synonym_count": 0, "synonyms": [], "reaction_count": 0,
                       "follower_count": 0, "is_following": False})
    return context


class CoreZeroProviderTests(unittest.TestCase):
    """core 流零 provider 访问(mock/spy 证明)。"""

    def test_core_returns_canonical_and_zero_provider_calls(self):
        from api.services import chemicals as svc
        rec = _Recorder()

        async def spy_pb(*a, **k):
            rec.bump("pb"); return None, None, False

        async def spy_cb(*a, **k):
            rec.bump("cb"); raise AssertionError("core 不得触碰 services.cb")

        async def go():
            db = _make_db(rec)
            fetch = await _fake_fetch()
            context = await _fake_context()
            from api.services import cb as cb_module
            from api.services import enrichment as enrichment_module
            with patch.object(svc, "fetch_chemicals", fetch), \
                 patch.object(svc, "fill_detail_context", context), \
                 patch.object(enrichment_module, "enqueue_chemical_if_needed", spy_pb), \
                 patch.object(cb_module, "get_externals_row", spy_cb), \
                 patch.object(cb_module, "cb_decide", spy_cb), \
                 patch.object(cb_module, "get_suppliers", spy_cb), \
                 patch.object(cb_module, "negative_is_fresh", spy_cb), \
                 patch.object(cb_module, "enqueue_cas_job", spy_cb):
                return await svc.get_chemical_detail(
                    db, 1, actor_id=None, priority=50, enrich="core")

        result = asyncio.run(go())
        self.assertEqual(result["id"], 1)
        self.assertEqual(result["preferred_name"], "water")
        self.assertIsNone(result["details"], "core details 必须为 None")
        self.assertEqual(result["enrichment"]["status"], "current")
        self.assertEqual(rec.calls.get("pb", 0), 0, "core 不得调 PB service")
        self.assertEqual(rec.calls.get("cb", 0), 0, "core 不得调 CB service")
        self.assertEqual(rec.calls.get("commit", 0), 0, "core 不得 commit provider job")


class FullOrchestrationTests(unittest.TestCase):
    """full 流编排: 两源 owner 各自调用、失败隔离、冲突事实保双源。"""

    def _full(self, pb_details=None, pb_exc=None, cb_row=None, cb_exc=None,
              cas="7732-18-5", cb_decision="serve_fresh", cb_suppliers=None,
              negative=False, locale=None, seen=None):
        from api.services import chemicals as svc

        pb_default = {
            "record_description": "PB desc",
            "xlogp": -0.5,
            "physical_properties": {"entries": {"Boiling Point": ["100 °C"]}},
            "fetched_at": "2026-09-01T00:00:00+00:00",
        }
        pb_payload = pb_details if pb_details is not None else pb_default

        async def go():
            db = _make_db(cas=cas)

            async def fake_pb(db_, cid, *, priority, allow_refresh=True, actor=None):
                if pb_exc is not None:
                    raise pb_exc
                return pb_payload, None, False

            async def fake_get_row(d, cid, locale=None):
                if cb_exc is not None:
                    raise cb_exc
                if seen is not None:
                    seen["requested_locale"] = locale
                return cb_row

            async def fake_decide(d, cid, locale="zh-CN", cb_number=None):
                if seen is not None:
                    seen.setdefault("decide", []).append(locale)
                return cb_decision

            async def fake_suppliers(d, cid):
                return cb_suppliers or []

            async def fake_negative(d, kind, **k):
                return negative

            values = list(CANONICAL_VALUES)
            if cas is None:
                values[11] = None
            fetch = await _fake_fetch(values)
            context = await _fake_context()
            from api.services import cb as cb_module
            from api.services import enrichment as enrichment_module

            async def fake_enqueue(d, *, chemical_id, cas_number, priority,
                                   locale="zh-CN", request_context=None,
                                   source_cb_number=None):
                if seen is not None:
                    seen["enqueue_locale"] = locale
                return 99

            with patch.object(svc, "fetch_chemicals", fetch), \
                 patch.object(svc, "fill_detail_context", context), \
                 patch.object(enrichment_module, "enqueue_chemical_if_needed", fake_pb), \
                 patch.object(cb_module, "get_externals_row", fake_get_row), \
                 patch.object(cb_module, "cb_decide", fake_decide), \
                 patch.object(cb_module, "get_suppliers", fake_suppliers), \
                 patch.object(cb_module, "negative_is_fresh", fake_negative), \
                 patch.object(cb_module, "enqueue_cas_job", fake_enqueue):
                return await svc.get_chemical_detail(
                    db, 1, actor_id=None, priority=50, enrich="full", locale=locale)

        return asyncio.run(go())

    def test_full_pb_cb_both_present(self):
        result = self._full(cb_row={"entry": {
            "identity": {"cn": "水", "en": "water"},
            "props": [{"key": "bp", "label": "沸点", "text": "100°C", "v": 100, "unit": "°C"}],
            "safety": {"急救": "清水冲洗"},
            "prose": [{"title": "用途", "text": "溶剂"}],
        }, "cb_number": "CB1", "locale": "zh-CN"}, cb_suppliers=[{"ref": "r1", "name": "SupA"}])
        d = result["details"]
        self.assertEqual(d["description"]["record_description"], "PB desc")
        self.assertEqual(d["properties"]["pb_computed"]["xlogp"], -0.5)
        self.assertEqual(d["names"]["cb_identity"]["cn"], "水")
        self.assertEqual(d["properties"]["cb_experimental"][0]["text"], "100°C")
        self.assertEqual(d["safety"]["cb_safety"]["急救"], "清水冲洗")
        self.assertEqual(d["industry"]["cb_uses"][0]["text"], "溶剂")
        self.assertEqual(d["suppliers"]["items"][0]["name"], "SupA")
        self.assertEqual(d["provenance"]["pubchem"]["state"], "current")
        self.assertEqual(d["provenance"]["cb"]["state"], "current")
        self.assertEqual(result["enrichment"]["sources"],
                         {"pubchem": "current", "cb": "current"})

    def test_full_conflict_facts_both_kept(self):
        """PB 物性与 CB 物性并存 — 相似字段两条独立证据, 无覆盖。"""
        result = self._full(cb_row={"entry": {
            "props": [{"key": "bp", "label": "沸点", "text": "99.9°C"}],
        }, "cb_number": "CB1", "locale": "zh-CN"})
        props = result["details"]["properties"]
        self.assertIn("Boiling Point", props["pb_physical_properties"]["entries"])
        self.assertEqual(props["cb_experimental"][0]["text"], "99.9°C")

    def test_full_pb_only(self):
        result = self._full(cb_row=None, cas=None)
        d = result["details"]
        self.assertEqual(d["description"]["record_description"], "PB desc")
        self.assertEqual(d["provenance"]["cb"]["state"], "none")
        self.assertFalse(d["provenance"]["cb"].get("applicable", True))

    def test_full_cb_only(self):
        result = self._full(pb_details={"record_description": None, "fetched_at": None},
                            cb_row={"entry": {"identity": {"cn": "水"}}, "cb_number": "CB1", "locale": "zh-CN"})
        d = result["details"]
        self.assertEqual(d["names"]["cb_identity"]["cn"], "水")
        self.assertEqual(d["provenance"]["pubchem"]["state"], "current")

    def test_full_pb_fail_cb_success_not_500(self):
        result = self._full(pb_exc=RuntimeError("pb down"),
                            cb_row={"entry": {"identity": {"cn": "水"}}, "cb_number": "CB1", "locale": "zh-CN"})
        d = result["details"]
        self.assertEqual(d["provenance"]["pubchem"]["state"], "unavailable")
        self.assertEqual(d["names"]["cb_identity"]["cn"], "水")
        self.assertEqual(result["enrichment"]["status"], "degraded")

    def test_full_cb_fail_pb_success_not_500(self):
        result = self._full(cb_exc=RuntimeError("cb down"))
        d = result["details"]
        self.assertEqual(d["provenance"]["cb"]["state"], "unavailable")
        self.assertEqual(d["description"]["record_description"], "PB desc")
        self.assertEqual(result["enrichment"]["status"], "degraded")

    def test_full_neither_source(self):
        result = self._full(pb_details={"record_description": None, "fetched_at": None},
                            cas=None)
        d = result["details"]
        self.assertIsNone(d["description"]["record_description"])
        self.assertEqual(result["enrichment"]["status"], "current")

    def test_full_absent_maps_none_not_error(self):
        result = self._full(cb_row=None, negative=True)
        self.assertEqual(result["details"]["provenance"]["cb"]["state"], "none")
        self.assertEqual(result["enrichment"]["sources"]["cb"], "none")

    def test_semantic_shape_no_provider_top_level(self):
        result = self._full(cb_row={"entry": {"identity": {}}, "cb_number": "CB1", "locale": "zh-CN"})
        for key in result["details"]:
            self.assertIn(key, ("description", "names", "properties", "safety",
                                "industry", "suppliers", "provenance"),
                          f"一级 key 必须是语义 section, 不允许 provider namespace: {key}")


class LocaleLifecycleChainTests(unittest.TestCase):
    """P1-1: 实际命中 locale 在 row selection → lifecycle decision →
    refresh enqueue 整条链不断(fake 记录收到的 locale, 锁死连接点)。"""

    def test_requested_ja_hit_ja_decides_ja(self):
        seen = {}
        self._full_locale(seen, cb_row={"entry": {"identity": {"cn": "x"}},
                                        "cb_number": "CB1", "locale": "ja"},
                           locale="ja")
        self.assertEqual(seen["requested_locale"], "ja")
        self.assertEqual(seen["decide"], ["ja"])

    def test_requested_ja_fallback_en_decides_en(self):
        seen = {}
        self._full_locale(seen, cb_row={"entry": {"identity": {"cn": "x"}},
                                        "cb_number": "CB1", "locale": "en"},
                           locale="ja")
        self.assertEqual(seen["requested_locale"], "ja")
        self.assertEqual(seen["decide"], ["en"])

    def test_stale_ja_enqueues_refresh_ja(self):
        seen = {}
        self._full_locale(seen, cb_row={"entry": {"identity": {"cn": "x"}},
                                        "cb_number": "CB1", "locale": "ja"},
                           locale="ja", cb_decision="enqueue_refresh")
        self.assertEqual(seen["decide"], ["ja"])
        self.assertEqual(seen["enqueue_locale"], "ja")

    def test_stale_fallback_en_enqueues_refresh_en(self):
        seen = {}
        self._full_locale(seen, cb_row={"entry": {"identity": {"cn": "x"}},
                                        "cb_number": "CB1", "locale": "en"},
                           locale="ja", cb_decision="enqueue_refresh")
        self.assertEqual(seen["decide"], ["en"])
        self.assertEqual(seen["enqueue_locale"], "en")

    def _full_locale(self, seen, **kwargs):
        FullOrchestrationTests()._full(**kwargs, seen=seen)


class RemovedSurfaceTests(unittest.TestCase):
    """/details、/externals、MCP externals tool 全部消失。"""

    def test_details_and_externals_endpoints_removed(self):
        from api import routes as routes_module
        for route in routes_module.router.routes:
            path = getattr(route, "path", "")
            self.assertNotIn("/details", path, "details 端点必须删除")
            self.assertNotIn("/externals", path, "externals 端点必须删除")

    def test_enrichment_router_unmounted(self):
        import api.main as main_module
        src = inspect.getsource(main_module)
        self.assertNotIn("enrichment_router", src)

    def test_mcp_no_externals_tool_count_13(self):
        from api.mcp_server import build_mcp_server
        tools = asyncio.run(build_mcp_server().list_tools())
        names = {tool.name for tool in tools}
        self.assertNotIn("get_chemical_externals", names)
        self.assertEqual(len(names), 13, f"MCP 工具数应为 13, 实际 {len(names)}")

    def test_agent_guide_no_externals_operation(self):
        import api.agent as agent_module
        src = inspect.getsource(agent_module)
        self.assertNotIn('"get_chemical_externals"', src)

    def test_llms_txt_no_externals_13_tools(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        with open(os.path.join(root, "web/public/llms.txt"), encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("externals", content)
        self.assertNotIn("get_chemical_externals", content)
        self.assertIn("13 个", content)


class McpCoreFullDifferenceTests(unittest.TestCase):
    """MCP get_chemical core/full 真有差异(full 才带 semantic detail)。"""

    def test_mcp_core_and_full_differ(self):
        from api.mcp_server import build_mcp_server
        from api.services import chemicals as chem_svc

        async def fake_detail(session, cid, *, actor_id, priority, enrich):
            if enrich == "core":
                return {"id": cid, "details": None,
                        "enrichment": {"status": "current"}}
            return {"id": cid,
                    "details": {"description": {"source": "pubchem", "record_description": "d"},
                                "names": {"cb_identity": {}, "cb_aliases": []}},
                    "enrichment": {"status": "current",
                                   "sources": {"pubchem": "current", "cb": "current"}}}

        async def go():
            with patch.object(chem_svc, "get_chemical_detail", fake_detail):
                server = build_mcp_server()
                core = await server.call_tool(
                    "get_chemical", {"chemical_id": 1, "enrich": "core"}, context=FakeCtx())
                full = await server.call_tool(
                    "get_chemical", {"chemical_id": 1, "enrich": "full"}, context=FakeCtx())
            return core, full

        core, full = asyncio.run(go())
        core_data = _extract(core)
        full_data = _extract(full)
        self.assertIsNone(core_data["details"])
        self.assertEqual(full_data["details"]["description"]["record_description"], "d")


class FakeCtx:
    def __init__(self, headers: dict | None = None):
        self.headers = dict(headers or {})


def _extract(result):
    """FastMCP call_tool 结果(CallToolResult/list/dict 形态差异)→ payload dict。"""
    if isinstance(result, dict):
        return result
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return data
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(result, "content", None)
    if content and isinstance(content, list) and content:
        import json as _json
        text = getattr(content[0], "text", None)
        if isinstance(text, str):
            return _json.loads(text)
    raise TypeError(f"无法从 {type(result)} 提取 payload")


class WebSourceContractTests(unittest.TestCase):
    """Web 源码断言: 无 /externals 请求; metadata core; 页面 full。"""

    def test_page_no_externals_uses_full_metadata_core(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        with open(os.path.join(
                root, "web/app/(site)/chemical/[id]/page.tsx"), encoding="utf-8") as f:
            page = f.read()
        import re
        api_calls = re.findall(r"apiGet[^`]*`([^`]+)`", page)
        self.assertTrue(api_calls, "页面应有 apiGet 调用")
        for call in api_calls:
            self.assertNotIn("/externals", call, f"页面不得请求 /externals: {call}")
        self.assertTrue(any("enrich=full" in c for c in api_calls),
                        "页面主请求必须 enrich=full")
        self.assertTrue(any("enrich=core" in c and "display" not in c for c in api_calls),
                        "metadata 必须使用 enrich=core")


class RealDbCoreFullTests(unittest.TestCase):
    """真链 PG: core 与 full 返回体确实不同(full 才查 provider)。"""

    def test_http_core_full_different_payload(self):
        url = test_db_or_skip()

        async def go():
            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
            from sqlalchemy.pool import NullPool
            from api.services import chemicals as svc

            def _dsn(u):
                base = u.split("?")[0]
                if base.startswith("postgresql://"):
                    base = "postgresql+asyncpg://" + base.split("://", 1)[1]
                return base

            engine = create_async_engine(_dsn(url), poolclass=NullPool)
            try:
                async with AsyncSession(engine) as session:
                    cid = (await session.execute(text(
                        "SELECT id FROM chemistry.chemicals ORDER BY id LIMIT 1"))).scalar()
                    if cid is None:
                        self.skipTest("test DB 无 chemicals 行")
                    core = await svc.get_chemical_detail(
                        session, int(cid), actor_id=None, priority=50, enrich="core")
                async with AsyncSession(engine) as s2:
                    full = await svc.get_chemical_detail(
                        s2, int(cid), actor_id=None, priority=50, enrich="full")
                return core, full
            finally:
                await engine.dispose()

        core, full = asyncio.run(go())
        self.assertIsNone(core["details"])
        self.assertIsNotNone(full["details"], "full 必须带 semantic detail")
        for key in ("description", "names", "properties", "safety",
                    "industry", "suppliers", "provenance"):
            self.assertIn(key, full["details"], f"semantic 一级 section {key} 缺失")


if __name__ == "__main__":
    unittest.main()
