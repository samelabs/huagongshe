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


class CjkTwoCharExactTierTests(unittest.TestCase):
    """两字 CJK exact 超时 hotfix 的判别测试(纯逻辑 + mock DB 行为断言)。"""

    # ---- 纯逻辑: 是否禁止 substring fallback ----

    def test_pure_two_cjk_blocks_fallback(self) -> None:
        from api.services.search import is_two_cjk_query

        self.assertTrue(is_two_cjk_query("甲醇"))
        self.assertTrue(is_two_cjk_query("乙醇"))

    def test_mixed_queries_keep_fallback(self) -> None:
        from api.services.search import is_two_cjk_query

        self.assertFalse(is_two_cjk_query("甲醇a"))  # normalize 后 甲醇a
        self.assertFalse(is_two_cjk_query("a甲醇"))
        self.assertFalse(is_two_cjk_query("甲醇-d4"))
        self.assertFalse(is_two_cjk_query("苯甲酸钠"))

    def test_allows_substring_fallback_matrix(self) -> None:
        from api.services.search import allows_substring_fallback
        from api.services.chemicals import MIN_FUZZY_NAME_LENGTH, name_query_width

        # 甲醇 width=4, 但 pure-two-CJK -> 禁
        self.assertEqual(name_query_width("甲醇"), 4)
        self.assertFalse(allows_substring_fallback("甲醇"))
        self.assertFalse(allows_substring_fallback("乙醇"))
        # width=3 的既有契约行为不变
        self.assertEqual(name_query_width("a甲"), 3)
        self.assertTrue(allows_substring_fallback("a甲"))  # A甲
        self.assertTrue(allows_substring_fallback("甲a"))  # 甲A
        self.assertTrue(allows_substring_fallback("甲醇a"))  # 甲醇A
        self.assertTrue(allows_substring_fallback("a甲醇"))  # A甲醇
        self.assertTrue(allows_substring_fallback("甲醇-d4"))
        self.assertTrue(allows_substring_fallback("苯甲酸钠"))
        # width=2 -> 禁(既有最短长度门槛)
        self.assertEqual(name_query_width("ab"), 2)
        self.assertFalse(allows_substring_fallback("ab"))
        self.assertLess(2, MIN_FUZZY_NAME_LENGTH)

    # ---- mock DB: exact miss 后第二条 substring SQL 是否执行 ----

    def _run_tier3(self, query: str, exact_ids: list):
        """直接调用 run_search_query 的 tier3 路径, mock db.execute 记录 SQL。"""
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

        class FakeDB:
            async def execute(self, sql_text, params=None):
                sql = str(sql_text)
                executed.append(sql)
                if "normalized = :nq" in sql:
                    return FakeResult(exact_ids)
                if "LIKE '%' || :nq" in sql:
                    return FakeResult([999999])
                return FakeResult([])

            async def rollback(self):
                pass

            async def commit(self):
                pass

        async def fetch_chemicals_stub(db, sql, params=None):
            return []

        db = FakeDB()
        real_fetch = search_service.fetch_chemicals
        search_service.fetch_chemicals = fetch_chemicals_stub
        try:
            chemicals, total, reactions, pending, canon, hit_id = asyncio.run(
                search_service.run_search_query(
                    db, query=query, mode="exact", canonical=None,
                    page=1, page_size=30, offset=0,
                )
            )
        finally:
            search_service.fetch_chemicals = real_fetch
        return executed, {"chemicals": chemicals, "total": total}

    def test_methanol_exact_hit_does_not_run_substring(self) -> None:
        # exact equality 命中(178719118) -> 不再执行 substring SQL
        executed, _ = self._run_tier3("甲醇", exact_ids=[178719118])
        self.assertTrue(any("normalized = :nq" in s for s in executed))
        self.assertFalse(any("LIKE '%' || :nq" in s for s in executed))

    def test_two_cjk_exact_miss_stops_before_substring(self) -> None:
        # 纯两字 CJK exact miss -> 不执行 substring, 快速空返回
        executed, result = self._run_tier3("囧氘", exact_ids=[])
        self.assertTrue(any("normalized = :nq" in s for s in executed))
        self.assertFalse(any("LIKE '%' || :nq" in s for s in executed))
        self.assertEqual(result.get("chemicals") or [], [])

    def test_width_three_mixed_query_exact_miss_runs_substring(self) -> None:
        # A甲: width=3(len=2) 既有契约允许 -> substring 必须执行
        executed, _ = self._run_tier3("A甲", exact_ids=[])
        self.assertTrue(any("normalized = :nq" in s for s in executed))
        self.assertTrue(any("LIKE '%' || :nq" in s for s in executed))

    def test_methanol_exact_miss_never_runs_substring(self) -> None:
        # 甲醇: 纯两字 CJK -> exact miss 时 LIKE 不执行
        executed, result = self._run_tier3("甲醇", exact_ids=[])
        self.assertTrue(any("normalized = :nq" in s for s in executed))
        self.assertFalse(any("LIKE '%' || :nq" in s for s in executed))
        self.assertEqual(result.get("chemicals") or [], [])

    def test_mixed_query_exact_miss_runs_substring(self) -> None:
        # 甲醇-d4: 混合查询 exact miss -> substring fallback 执行
        executed, _ = self._run_tier3("甲醇-d4", exact_ids=[])
        self.assertTrue(any("normalized = :nq" in s for s in executed))
        self.assertTrue(any("LIKE '%' || :nq" in s for s in executed))

    def test_three_plus_cjk_exact_miss_runs_substring(self) -> None:
        # 苯甲酸钠: ≥3 字 exact miss -> substring fallback 执行
        executed, _ = self._run_tier3("苯甲酸钠", exact_ids=[])
        self.assertTrue(any("normalized = :nq" in s for s in executed))
        self.assertTrue(any("LIKE '%' || :nq" in s for s in executed))

    def test_exact_precedes_substring_in_source_order(self) -> None:
        import inspect
        from api.services import search as search_service

        source = inspect.getsource(search_service.run_search_query)
        self.assertLess(
            source.index("WHERE normalized = :nq"),
            source.index("WHERE normalized LIKE '%' || :nq || '%'"),
            "exact equality 必须先于 substring 执行",
        )

    def test_no_new_identifier_logic_or_canonical_change(self) -> None:
        import inspect
        from api.services import search as search_service

        source = inspect.getsource(search_service.run_search_query)
        self.assertNotIn("hcid:", source)
        self.assertIn("nq = normalize_name(query)", source)


if __name__ == "__main__":
    unittest.main()
