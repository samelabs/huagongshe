from __future__ import annotations

import os
import inspect
import unittest

from fastapi import HTTPException

os.environ.setdefault("HGS_DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/test")

from api.core.rate_limit import is_loopback_host
from api import routes
from api.services.enrichment import display_details
from api.chemistry import normalize_doi
from api.services import chemicals as chemicals_service
from api.services.chemicals import bounded_substructure_smiles


class StructureSearchContractTests(unittest.TestCase):
    def test_exact_search_is_not_cached_with_mutable_user_reactions(self) -> None:
        source = inspect.getsource(routes.search)
        self.assertEqual(source.count('if mode != "exact":'), 2)

    def test_doi_lookup_uses_separate_indexable_sources(self) -> None:
        from api.services.chemicals import reaction_lookup
        source = inspect.getsource(reaction_lookup)
        self.assertIn("lower(rx.doi)=:doi", source)
        self.assertIn("WHERE lower(doi)=:doi", source)
        self.assertNotIn("COALESCE(rx.doi,rp.doi)=:doi", source)
        self.assertNotIn("rows_by_id", source)
        self.assertIn("ORDER BY reaction_id,id", source)

    def test_doi_normalization_accepts_url_and_case(self) -> None:
        self.assertEqual(
            normalize_doi("https://doi.org/10.1039/C8SC04228D"),
            "10.1039/c8sc04228d",
        )
        self.assertIsNone(normalize_doi("not-a-doi"))

    def test_exact_search_uses_indexable_dtxsid_and_bounded_names(self) -> None:
        from api.services import search as search_service
        source = inspect.getsource(search_service.run_search_query)
        self.assertIn("c.dtxsid = :uq", source)
        self.assertNotIn("upper(c.dtxsid)", source)
        self.assertIn("MIN_FUZZY_NAME_LENGTH", source)

    def test_bounded_substructure_accepts_specific_structure(self) -> None:
        smiles = "CC(=O)Oc1ccccc1C(=O)O"
        self.assertEqual(bounded_substructure_smiles(smiles), smiles)

    def test_bounded_substructure_rejects_broad_structure(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            bounded_substructure_smiles("c1ccccc1")
        self.assertEqual(raised.exception.status_code, 422)

    def test_only_real_loopback_addresses_are_trusted(self) -> None:
        self.assertTrue(is_loopback_host("127.0.0.1"))
        self.assertTrue(is_loopback_host("::1"))
        self.assertFalse(is_loopback_host("127.0.0.1.example.com"))
        self.assertFalse(is_loopback_host("203.0.113.8"))

    def test_structure_modes_share_the_public_read_gate(self) -> None:
        """结构模式登录墙(H1 保持): mode!=exact 需已鉴权 actor, exact 匿名照旧.
        墙由 c75424c 建立、73f2ab3 拆除、2026-08-26 重建(拆墙评估漏算并发面).
        H1 方案 D 重命名 dependency 为 public_or_actor, 本墙语义不变。
        """
        source = inspect.getsource(routes.search)
        self.assertIn('if mode != "exact" and actor is None', source)
        for endpoint in (routes.chemical_substructure, routes.chemical_similarity):
            src = inspect.getsource(endpoint)
            self.assertIn("Depends(public_or_actor)", src)
            self.assertIn("actor is None", src)

    def test_chemical_reaction_counts_avoid_visible_reaction_point_lookups(self) -> None:
        summary_source = inspect.getsource(routes.reaction_summaries)
        detail_source = inspect.getsource(chemicals_service.fill_detail_context)
        self.assertIn("total_all", summary_source)
        self.assertIn("excluded", summary_source)
        self.assertIn("NOT EXISTS", summary_source)
        self.assertIn("total_reactions", detail_source)
        self.assertIn("excluded_reactions", detail_source)

    def test_display_details_bounds_page_evidence_without_mutating_source(self) -> None:
        original = {
            "source_references": {"1": "unused by page"},
            "toxicity": {"entries": {f"item-{i}": list(range(10)) for i in range(20)}},
        }
        result = display_details(original)
        self.assertNotIn("source_references", result)
        self.assertEqual(len(result["toxicity"]["entries"]), 12)
        self.assertEqual(len(result["toxicity"]["entries"]["item-0"]), 6)
        self.assertEqual(len(original["toxicity"]["entries"]), 20)


class SearchSystemGovernanceTests(unittest.TestCase):
    """Search System Governance 判别测试: exact 短路 / fuzzy 资格 / 统一分页 / has_more / 零 count。"""

    # ---- 纯逻辑: fuzzy substring 资格(normalize 后 >= 3 字符) ----

    def test_fuzzy_eligibility_matrix(self) -> None:
        from api.services.search import allows_fuzzy_substring

        # 两字符(无论 CJK/混合/拉丁)一律不进 substring
        self.assertFalse(allows_fuzzy_substring("甲醇"))
        self.assertFalse(allows_fuzzy_substring("a甲"))
        self.assertFalse(allows_fuzzy_substring("甲a"))
        self.assertFalse(allows_fuzzy_substring("ab"))
        # >=3 字符可 fuzzy
        self.assertTrue(allows_fuzzy_substring("苯甲酸"))
        self.assertTrue(allows_fuzzy_substring("苯甲酸钠"))
        self.assertTrue(allows_fuzzy_substring("benzoic"))
        self.assertTrue(allows_fuzzy_substring("甲醇-d4"))

    def test_query_acceptance_unchanged(self) -> None:
        # 入口规则仍是 name_query_width >= MIN_FUZZY_NAME_LENGTH
        from api.services.chemicals import MIN_FUZZY_NAME_LENGTH, name_query_width

        self.assertEqual(name_query_width("ab"), 2)
        self.assertLess(name_query_width("ab"), MIN_FUZZY_NAME_LENGTH)  # AB 入口即拒
        self.assertGreaterEqual(name_query_width("a甲"), MIN_FUZZY_NAME_LENGTH)  # A甲 合法

    def test_fuzzy_window_dynamic_prefix_bounded(self) -> None:
        # 动态 deterministic 前缀窗口: page1→31, page2→61, page3→91,
        # page_size=100/page1→101; 上限 2001(API page≤20×page_size≤100)
        from api.services.search import FUZZY_CANDIDATE_CAP, candidate_window

        self.assertEqual(candidate_window(0, 30), 31)
        self.assertEqual(candidate_window(30, 30), 61)
        self.assertEqual(candidate_window(60, 30), 91)
        self.assertEqual(candidate_window(0, 100), 101)
        self.assertEqual(candidate_window(1900, 100), 2001)
        self.assertEqual(candidate_window(10_000, 100), FUZZY_CANDIDATE_CAP)

    # ---- mock DB: run_name_search 行为断言 ----

    def _run_name_search(self, query: str, page=1, page_size=30, exact_hit=None, fuzzy_hit=None):
        """mock db: exact 阶段三查询 / fuzzy 阶段三查询分别可注入结果。"""
        import asyncio
        from api.services import search as search_service

        executed: list[str] = []

        class FakeResult:
            def __init__(self, ids):
                self._ids = ids

            def scalars(self):
                return self

            def all(self):
                return list(self._ids)

        exact_hit = exact_hit or {}
        fuzzy_hit = fuzzy_hit or {}

        class FakeDB:
            async def execute(self, sql_text, params=None):
                sql = str(sql_text)
                executed.append(sql)
                if "preferred_name = ANY" in sql:
                    return FakeResult(exact_hit.get("preferred", []))
                if "iupac_name = ANY" in sql:
                    return FakeResult(exact_hit.get("iupac", []))
                if "normalized = :nq" in sql:
                    return FakeResult(exact_hit.get("name_index", []))
                if "preferred_name ILIKE" in sql:
                    return FakeResult(fuzzy_hit.get("preferred", []))
                if "iupac_name ILIKE" in sql:
                    return FakeResult(fuzzy_hit.get("iupac", []))
                if "normalized LIKE" in sql:
                    return FakeResult(fuzzy_hit.get("name_index", []))
                return FakeResult([])

            async def rollback(self):
                pass

            async def commit(self):
                pass

        async def fetch_chemicals_stub(db, sql, params=None):
            executed.append(str(sql))
            ids = params.get("ids") if params else None
            return [{"id": i} for i in (ids or [])]

        db = FakeDB()
        real_fetch = search_service.fetch_chemicals
        search_service.fetch_chemicals = fetch_chemicals_stub
        try:
            chemicals, has_more = asyncio.run(search_service.run_name_search(
                db, query, page_size, (page - 1) * page_size,
            ))
        finally:
            search_service.fetch_chemicals = real_fetch
        return executed, chemicals, has_more

    def test_exact_hit_short_circuits_no_substring(self) -> None:
        # exact 命中 -> 三个 LIKE substring SQL 一个都不执行
        executed, chemicals, has_more = self._run_name_search(
            "benzoic acid", exact_hit={"preferred": [243]},
        )
        self.assertEqual([c["id"] for c in chemicals], [243])
        self.assertFalse(has_more)
        self.assertFalse(any("ILIKE" in s for s in executed))

    def test_exact_miss_two_char_no_substring(self) -> None:
        # 甲醇 / 囧氘 / A甲 / 甲A: exact miss -> 无 LIKE, 快速空
        for q in ("甲醇", "囧氘", "A甲", "甲A"):
            executed, chemicals, _ = self._run_name_search(q)
            self.assertEqual(chemicals, [], q)
            self.assertFalse(any("ILIKE" in s for s in executed), q)

    def test_exact_miss_three_char_runs_fuzzy(self) -> None:
        # 苯甲酸 / benzoic: exact miss -> fuzzy 执行, 且全部 fuzzy SQL 为
        # deterministic ID 流(ORDER BY id + 固定 cap, 不依赖无序窗口)
        for q in ("苯甲酸", "benzoic"):
            executed, chemicals, has_more = self._run_name_search(
                q, fuzzy_hit={"preferred": list(range(31))},
            )
            self.assertTrue(any("preferred_name ILIKE" in s for s in executed), q)
            self.assertEqual(len(chemicals), 30)
            self.assertTrue(has_more)
            for s in executed:
                if "ILIKE" in s:
                    self.assertIn("ORDER BY", s)  # deterministic candidate stream

    def test_fuzzy_rank_tier_order_and_dedup(self) -> None:
        # tier1(preferred={1,3,5}) 全排 tier2({2}) 前, tier3({9}) 最后; 跨 tier 去重(3,1)
        executed, chemicals, _ = self._run_name_search(
            "benzoic", page=1, page_size=30,
            fuzzy_hit={"preferred": [5, 3, 1], "iupac": [3, 2], "name_index": [9, 1]},
        )
        self.assertEqual([c["id"] for c in chemicals], [1, 3, 5, 2, 9])

    def test_hydrate_preserves_rank_order_across_tiers(self) -> None:
        # hydrate 不得用 ORDER BY c.id 抹平候选 rank: 跨 tier 且 id 逆序
        # (preferred=[900], iupac=[10], name_index=[5]) 最终顺序必须是
        # 900, 10, 5 —— 不能被 SQL 顺序改成 5, 10, 900。
        # fuzzy 锁一例:
        executed, chemicals, _ = self._run_name_search(
            "benzoic", page=1, page_size=30,
            fuzzy_hit={"preferred": [900], "iupac": [10], "name_index": [5]},
        )
        self.assertEqual([c["id"] for c in chemicals], [900, 10, 5])
        # hydrate SQL 本身不得再 ORDER BY c.id 决定最终顺序
        hydrate_sqls = [s for s in executed if "id = ANY" in s]
        self.assertTrue(hydrate_sqls)
        for s in hydrate_sqls:
            self.assertNotIn("ORDER BY", s)
        # exact 同锁一例:
        executed, chemicals, _ = self._run_name_search(
            "苯甲酸钠", page=1, page_size=30,
            exact_hit={"preferred": [900], "iupac": [10], "name_index": [5]},
        )
        self.assertEqual([c["id"] for c in chemicals], [900, 10, 5])
        hydrate_sqls = [s for s in executed if "id = ANY" in s]
        self.assertTrue(hydrate_sqls)
        for s in hydrate_sqls:
            self.assertNotIn("ORDER BY", s)

    def test_fuzzy_all_sources_deterministic_and_no_offset(self) -> None:
        # 每页三条 fuzzy SQL 均为 deterministic 前缀(ORDER BY id + :window 动态),
        # 无 source OFFSET; merged pagination 稳定(page1/page2 同语义连续切页)
        e1, p1_chem, p1_more = self._run_name_search(
            "benzoic", page=1, page_size=30, fuzzy_hit={"preferred": list(range(2001))},
        )
        e2, p2_chem, p2_more = self._run_name_search(
            "benzoic", page=2, page_size=30, fuzzy_hit={"preferred": list(range(2001))},
        )
        self.assertEqual([c["id"] for c in p1_chem], list(range(0, 30)))
        self.assertEqual([c["id"] for c in p2_chem], list(range(30, 60)))
        self.assertTrue(p1_more) and self.assertTrue(p2_more)
        for executed in (e1, e2):
            for s in executed:
                if "ILIKE" in s:
                    self.assertIn("ORDER BY", s)  # deterministic candidate stream
                self.assertNotIn("OFFSET", s)

    def test_has_more_comes_from_prefix_window(self) -> None:
        # has_more 语义 = 窗口(offset+page_size+1)内是否还有下一页
        # fuzzy 只回 30 条(< window 31) -> has_more=False
        _, _, more = self._run_name_search(
            "benzoic", page=1, page_size=30, fuzzy_hit={"preferred": list(range(30))},
        )
        self.assertFalse(more)
        # fuzzy 回 31 条(== window) -> has_more=True
        _, _, more = self._run_name_search(
            "benzoic", page=1, page_size=30, fuzzy_hit={"preferred": list(range(31))},
        )
        self.assertTrue(more)

    def test_no_count_sql_in_name_search(self) -> None:
        # 名称路径不允许任何 count(*) SQL
        executed, _, _ = self._run_name_search("苯甲酸")
        self.assertFalse(any("count(" in s for s in executed))

    # ---- run_search_query 契约: has_more / total ----

    def test_run_search_query_name_count_removed(self) -> None:
        import inspect
        from api.services import search as search_service

        src = inspect.getsource(search_service.run_search_query)
        # 名称双列 OR count 已删除; identifier count 保留
        self.assertNotIn("OR c.iupac_name ILIKE", src)
        self.assertIn("SELECT count(*) FROM chemistry.chemicals c", src)

    def test_routes_response_includes_has_more(self) -> None:
        import inspect
        from api import routes as routes_module

        src = inspect.getsource(routes_module.search)
        self.assertIn('"has_more": has_more', src)

    def test_cas_miss_no_sync_fetch_in_critical_path(self) -> None:
        import inspect
        from api.services import search as search_service

        src = inspect.getsource(search_service.run_search_query)
        # 同步外呼已从 CAS miss 分支移除(仅注释提及); import 面不再引入
        self.assertNotIn("import sync_fetch_and_store", src.replace("(\n", "("))
        self.assertNotIn("await sync_fetch_and_store", src)

    def test_structure_modes_has_more_semantics(self) -> None:
        # substructure/similarity 调 run_search_query: ①不依赖 name_has_more
        # (无 unbound variable); ②has_more 恢复本轮前语义:
        # total!=None → page*page_size < total; total=None → 当前页满则可能还有
        import asyncio
        from unittest.mock import patch, MagicMock, AsyncMock
        from api.services import search as search_service

        def run(mode, snapshot_ids, chemicals_len, page=1, page_size=30, sim=0.9):
            # similarity 行需带 similarity 字段(阈值过滤用); 满窗全过阈值且
            # 窗外未知 → cut_inside=False → total=None。
            fake_rows = [
                {"id": i, "similarity": sim} if mode == "similarity" else {"id": i}
                for i in range(chemicals_len)
            ]
            db = MagicMock()
            db.execute = AsyncMock(return_value=MagicMock(scalar=lambda: 0))
            # 阿司匹林 SMILES(13 重原子) — 过 bounded_substructure_smiles 的
            # ≥10 重原子闸门, CCO(3) 会被 422 挡。
            smiles = "CC(=O)Oc1ccccc1C(=O)O"
            if mode == "substructure":
                # snapshot: (db, canonical) -> ids; hydrate: rows
                # total 由 _snapshot_total(真实函数)从 ids 长度推导, 不 mock。
                with patch.object(search_service, "fetch_chemicals", new=AsyncMock(return_value=fake_rows)), \
                     patch("api.services.chemicals.substructure_snapshot", new=AsyncMock(return_value=list(snapshot_ids))), \
                     patch("api.services.chemicals.hydrate_chemicals", new=AsyncMock(return_value=fake_rows)):
                    return asyncio.run(search_service.run_search_query(
                        db, smiles, mode, smiles, page, page_size,
                        (page - 1) * page_size,
                    ))
            else:  # similarity
                with patch.object(search_service, "fetch_chemicals", new=AsyncMock(return_value=fake_rows)), \
                     patch("api.services.search.reaction_lookup", new=AsyncMock(return_value=[])):
                    return asyncio.run(search_service.run_search_query(
                        db, smiles, mode, smiles, page, page_size,
                        (page - 1) * page_size,
                    ))

        # substructure: snapshot 100 ids(未满 cap) -> total=100, has_more=1*30<100=True
        result = run("substructure", range(100), 30)
        self.assertEqual(result[1], 100)
        self.assertTrue(result[6])
        # substructure: snapshot 恰 30 ids -> total=30, has_more=1*30<30=False
        result = run("substructure", range(30), 30)
        self.assertEqual(result[1], 30)
        self.assertFalse(result[6])
        # similarity: total=None(prefix 满窗未 cut) + 当前页满 -> 保守 True
        result = run("similarity", None, 30)
        self.assertIsNone(result[1])
        self.assertTrue(result[6])
        # similarity: total=None(prefix 不满 → 精确 total) + 当前页不满 -> False
        # (10 行 < window 30 → cut_inside → total=10, has_more=1*30<10=False)
        result = run("similarity", None, 10)
        self.assertEqual(result[1], 10)
        self.assertFalse(result[6])
        # similarity page>=2(收口 0914 #1): qualifying 是从第 1 条起的完整
        # 前缀, cut_inside 时精确 total=len(qualifying), 与页码无关 —
        # 旧实现 offset+len(qualifying) 每页虚增 page_size(35 条 p2 报 65)。
        result = run("similarity", None, 35, page=2)
        self.assertEqual(result[1], 35)
        self.assertFalse(result[6])
        self.assertEqual(len(result[0]), 5)
        # similarity page>=2 满窗未 cut 语义不变: total 仍 None
        result = run("similarity", None, 100, page=2)
        self.assertIsNone(result[1])
        self.assertTrue(result[6])


if __name__ == "__main__":
    unittest.main()
