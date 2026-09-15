"""Structure Search 收口回归(0915): q+mode 唯一路径 + capped 契约。

审计背景: /api/chemicals/{id}/substructure|similarity 已删除, 前端不得再
引用; capped=true 表示 substructure snapshot 达到产品上限 250, 数据库真实
总匹配数未知 — total 不得被冒充数据库真实总数。

纯静态/纯函数检查, 不依赖 DB; capped 语义经 run_search_query 单元级驱动
(mock snapshot), 不到真实库。
"""
from __future__ import annotations

import inspect
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("HGS_DATABASE_URL", os.environ.get("TEST_DATABASE_URL", ""))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
        return handle.read()


class ChemicalDetailStructureLinksTests(unittest.TestCase):
    """chemical detail: 结构搜索入口必须是 q+mode, 无 chemical_id。"""

    def test_links_are_q_plus_mode_without_chemical_id(self):
        source = _read(os.path.join("web", "app", "(site)", "chemical", "[id]", "page.tsx"))
        self.assertIn(
            "`/search?q=${encodeURIComponent(chemical.smiles)}&mode=substructure`", source,
            "substructure 入口必须是 /search?q=<smiles>&mode=substructure",
        )
        self.assertIn(
            "`/search?q=${encodeURIComponent(chemical.smiles)}&mode=similarity`", source,
            "similarity 入口必须是 /search?q=<smiles>&mode=similarity",
        )
        self.assertNotIn("chemical_id=", source, "detail 页不得再生成 chemical_id 查询参数")

    def test_links_gated_on_session_and_smiles(self):
        source = _read(os.path.join("web", "app", "(site)", "chemical", "[id]", "page.tsx"))
        # 无 smiles 时不得渲染结构搜索链接: 链接块必须同时受 hasSession 与
        # chemical.smiles 门控
        self.assertRegex(source, r"hasSession\s*\?\s*\(chemical\.smiles\s*\?")


class SearchPageNoRetiredEndpointsTests(unittest.TestCase):
    """SearchPage: 不再引用 retired /chemicals/{id}/substructure|similarity。"""

    def test_search_page_has_no_chemical_id_structure_branch(self):
        source = _read(os.path.join("web", "app", "(site)", "search", "page.tsx"))
        # 不得再有 structure-search 的 chemical_id 查询参数/变量/分支。
        # 注意: cas_fetch_chemical_id 是 CAS 直跳响应字段(合法), 不在禁列。
        self.assertNotIn("params.chemical_id", source, "SearchParams 不得再有 chemical_id")
        self.assertNotIn("chemicalId", source, "chemicalId 变量/分支应整体删除")
        self.assertNotIn("chemical_id=", source, "不得生成 chemical_id= 查询参数")
        self.assertNotIn("RelatedResponse", source, "chemicalId 专用 dead type 应删除")
        self.assertNotIn("v2:substructure:", source)
        self.assertNotIn("v2:similarity:", source)
        # 唯一结构检索路径: /search API 以 q + mode 调用
        self.assertIn("`/search?q=${encodeURIComponent(q)}&mode=${mode}", source)

    def test_web_tree_no_retired_endpoint_calls(self):
        offenders: list[str] = []
        for dirpath, _dirnames, filenames in os.walk(os.path.join(ROOT, "web")):
            if "node_modules" in dirpath or ".next" in dirpath:
                continue
            for name in filenames:
                if not name.endswith((".ts", ".tsx")):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
                if "/substructure" in text or "/similarity" in text:
                    # 允许出现的是 /search?...&mode=substructure 形态, 不允许
                    # 直接调 /chemicals/{id}/substructure|similarity
                    for token in ("`/chemicals/${chemicalId}/${mode}",
                                  "/chemicals/${id}/substructure", "/chemicals/${id}/similarity"):
                        if token in text:
                            offenders.append(os.path.relpath(path, ROOT))
                            break
        self.assertEqual([], offenders)


class CappedContractTests(unittest.TestCase):
    """capped 语义: <250 → false; =250 snapshot → true; similarity 恒 false。"""

    SMILES = "CC(=O)Oc1ccccc1C(=O)O"  # 阿司匹林, 13 重原子 — 过 ≥10 闸门

    def _run_substructure(self, snapshot_ids):
        import asyncio

        from api.services import search as search_service

        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar=lambda: 0))
        db.rollback = AsyncMock()
        db.commit = AsyncMock()
        with patch.object(search_service, "fetch_chemicals", new=AsyncMock(return_value=[])), \
             patch("api.services.chemicals.substructure_snapshot",
                   new=AsyncMock(return_value=list(snapshot_ids))), \
             patch("api.services.chemicals.hydrate_chemicals", new=AsyncMock(return_value=[])):
            return asyncio.run(search_service.run_search_query(
                db, self.SMILES, "substructure", self.SMILES, 1, 30, 0,
            ))

    def test_substructure_below_cap_capped_false(self):
        result = self._run_substructure(range(249))
        self.assertEqual(result[7], False, "snapshot 249 < 250 → capped 必须 false")
        self.assertEqual(result[1], 249, "未触顶 → total 为完整匹配集大小")

    def test_substructure_at_cap_capped_true(self):
        result = self._run_substructure(range(250))
        self.assertEqual(result[7], True, "snapshot 250 = 上限 → capped 必须 true")
        self.assertIsNone(result[1], "中途页 total=None(更多结果), 不冒充真实总数")

    def test_similarity_mode_capped_false(self):
        import asyncio

        from api.services import search as search_service

        rows = [{"id": i, "similarity": 0.9} for i in range(30)]
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar=lambda: 0))
        with patch.object(search_service, "fetch_chemicals", new=AsyncMock(return_value=rows)), \
             patch.object(search_service, "reaction_lookup", new=AsyncMock(return_value=[])):
            result = asyncio.run(search_service.run_search_query(
                db, self.SMILES, "similarity", self.SMILES, 1, 30, 0,
            ))
        self.assertFalse(result[7], "similarity 模式 capped 恒 false")

    def test_routes_response_includes_capped(self):
        from api import routes as routes_module

        src = inspect.getsource(routes_module.search)
        self.assertIn('"capped": capped', src)


class CappedUiWordingTests(unittest.TestCase):
    """capped 展示语义: UI 不得把 250 写成数据库真实总数。"""

    def test_capped_wording_present_and_factual(self):
        i18n = _read(os.path.join("web", "lib", "i18n.ts"))
        self.assertIn("结果集已触及结构搜索返回上限", i18n, "必须有 capped 事实语义文案")
        # capped 文案不得把任何数字包装成产品上限(不得依赖 total/页长度冒充)
        capped_line = next(
            line for line in i18n.splitlines() if "showingCappedRange" in line
        )
        self.assertNotIn("${total}", capped_line)
        self.assertNotIn("${n}", capped_line)

    def test_search_page_capped_call_has_no_total_fallback(self):
        """capped=true && total=null && 页满 30 条时不得显示"上限 30 条":
        调用点禁止 total ?? chemicals.length 兜底(页长度≠产品上限)。"""
        source = _read(os.path.join("web", "app", "(site)", "search", "page.tsx"))
        self.assertIn(
            "t.search.showingCappedRange(start, shown)",
            source,
            "capped 文案只接收 start/end, 不传 total 兜底",
        )
        self.assertNotIn(
            "showingCappedRange(start, shown, total",
            source,
            "capped 调用不得携带 total/页长度",
        )

    def test_capped_first_page_30_items_never_shows_cap_30(self):
        """行为渲染: capped=true + total=null + 第一页 30 条 → 文案不得出现
        "上限 30 条"(页长度冒充产品上限)。直接以 i18n 模板渲染验证。"""
        import re as _re

        i18n = _read(os.path.join("web", "lib", "i18n.ts"))
        match = _re.search(
            r"showingCappedRange:\s*\(start: number, end: number\)\s*=>\s*`([^`]*)`", i18n
        )
        self.assertIsNotNone(match, "showingCappedRange 必须只接收 (start, end)")
        rendered = match.group(1).replace("${start}", "1").replace("${end}", "30")
        self.assertNotIn("上限 30 条", rendered, f"capped 首页 30 条不得冒充产品上限: {rendered}")
        self.assertIn("结构搜索返回上限", rendered)
        self.assertIn("未知", rendered)

    def test_search_page_uses_capped_wording_when_capped(self):
        source = _read(os.path.join("web", "app", "(site)", "search", "page.tsx"))
        self.assertIn("showingCappedRange", source, "capped 时必须切 capped 文案")
        # capped 分支不得回落到"共 N 条"话术: capped 优先于 showingRange
        capped_pos = source.find("showingCappedRange")
        ternary_pos = source.find("t.search.showingCappedRange(")
        self.assertGreater(capped_pos, -1)
        self.assertGreater(ternary_pos, -1)


class StructurePaginationKeepsModeTests(unittest.TestCase):
    """structure pagination 保留 mode: load-more 链接必须带 mode。"""

    def test_load_more_keeps_mode_and_q(self):
        source = _read(os.path.join("web", "app", "(site)", "search", "page.tsx"))
        self.assertIn(
            "`/search?q=${encodeURIComponent(q)}${mode !== \"exact\" ? `&mode=${mode}` : \"\"}&page=${page + 1}`",
            source,
            "翻页链接必须保留 q, structure 模式必须保留 mode",
        )


class StructureHasMorePage20Tests(unittest.TestCase):
    """page20 has_more=false(0914 #2 收口) + similarity page2 total 回归。"""

    def test_routes_clamps_has_more_at_page_20(self):
        import asyncio

        from unittest.mock import AsyncMock as _AsyncMock

        import api.routes as routes_module

        async def fake_run(db, query, mode, canonical, page, page_size, offset, **kw):
            return [], 1000, [], False, canonical, None, True, False

        captured: dict = {}

        async def fake_cache_get(_key):
            return None

        async def fake_cache_set(key, data, ttl=0):
            captured["data"] = data

        db = MagicMock()
        db.execute = _AsyncMock(return_value=MagicMock(scalar=lambda: 0))
        db.rollback = _AsyncMock()

        actor = MagicMock()
        actor.id = 999

        with patch.object(routes_module, "run_search_query", fake_run), \
             patch.object(routes_module, "cache_get", fake_cache_get), \
             patch.object(routes_module, "cache_set", fake_cache_set), \
             patch.object(routes_module, "structure_enter", _AsyncMock(return_value=["h"])), \
             patch.object(routes_module, "structure_exit", _AsyncMock()):
            data = asyncio.run(routes_module.search(
                actor=actor, q="CC(=O)Oc1ccccc1C(=O)O", mode="substructure",
                threshold=0.7, page=20, page_size=30, db=db,
            ))
        self.assertFalse(data["has_more"], "page=20 已达契约上限, has_more 必须 false")

    def test_similarity_page2_total_regression(self):
        """similarity page2: cut_inside 时 total=精确数(不随页码虚增)。

        page2/page_size30 → window=60; mock 返回 50 行(< window)且全部
        过阈值 → cut_inside → total=len(qualifying)=50(与页码无关),
        旧实现会虚增成 offset+50=80。
        """
        import asyncio

        from api.services import search as search_service

        rows = [{"id": i, "similarity": 0.9} for i in range(50)]
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar=lambda: 0))
        with patch.object(search_service, "fetch_chemicals", new=AsyncMock(return_value=rows)), \
             patch.object(search_service, "reaction_lookup", new=AsyncMock(return_value=[])):
            result = asyncio.run(search_service.run_search_query(
                db, "CC(=O)Oc1ccccc1C(=O)O", "similarity", "CC(=O)Oc1ccccc1C(=O)O",
                2, 30, 30,
            ))
        self.assertEqual(result[1], 50, "page2 cut_inside: total 必须是精确 50, 不虚增为 80")
        self.assertEqual(len(result[0]), 20)
        self.assertFalse(result[6])

