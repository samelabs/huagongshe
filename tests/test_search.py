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
    """两字 CJK exact 超时 hotfix 的判别测试(源码契约, 无 DB)。"""

    def _tier3_source(self) -> str:
        import inspect
        from api.services import search as search_service

        return inspect.getsource(search_service.run_search_query)

    def test_tier3_runs_exact_normalized_before_substring(self) -> None:
        source = self._tier3_source()
        exact_pos = source.index("WHERE normalized = :nq")
        like_pos = source.index("WHERE normalized LIKE '%' || :nq || '%'")
        self.assertLess(exact_pos, like_pos, "exact equality 必须先于 substring 执行")

    def test_two_char_cjk_blocks_substring_fallback(self) -> None:
        source = self._tier3_source()
        self.assertIn("cjk_len != 2", source)

    def test_two_char_cjk_exact_miss_returns_without_substring(self) -> None:
        source = self._tier3_source()
        self.assertIn("if not tertiary_ids and len(nq) >= 3 and cjk_len != 2:", source)

    def test_longer_names_still_use_substring_fallback(self) -> None:
        source = self._tier3_source()
        self.assertIn("len(nq) >= 3", source)

    def test_no_new_identifier_logic_or_canonical_change(self) -> None:
        source = self._tier3_source()
        self.assertNotIn("hcid:", source)
        # canonical name 未被重定义: normalize_name 仍为唯一归一入口
        self.assertIn("nq = normalize_name(query)", source)

    def test_cjk_length_computation(self) -> None:
        def cjk_len(s: str) -> int:
            return sum(
                1 for ch in s
                if "\u4e00" <= ch <= "\u9fff" or "\u3040" <= ch <= "\u30ff"
                or "\uac00" <= ch <= "\ud7af"
            )
        self.assertEqual(cjk_len("甲醇"), 2)
        self.assertEqual(cjk_len("乙醇"), 2)
        self.assertEqual(cjk_len("苯甲酸钠"), 4)
        self.assertEqual(cjk_len("Aspirin"), 0)
        self.assertEqual(cjk_len("甲醇A"), 2)


if __name__ == "__main__":
    unittest.main()
