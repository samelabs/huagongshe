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
from api.routes import bounded_substructure_smiles


class StructureSearchContractTests(unittest.TestCase):
    def test_exact_search_is_not_cached_with_mutable_user_reactions(self) -> None:
        source = inspect.getsource(routes.search)
        self.assertEqual(source.count('if mode != "exact":'), 2)

    def test_doi_lookup_uses_separate_indexable_sources(self) -> None:
        source = inspect.getsource(routes.reaction_lookup)
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
        source = inspect.getsource(routes.search)
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
        """结构模式登录墙: mode!=exact 需已鉴权 actor, exact 匿名照旧(SSR).

        墙由 c75424c 建立、73f2ab3 拆除、2026-08-26 重建(拆墙评估漏算并发面).
        """
        source = inspect.getsource(routes.search)
        self.assertIn('if mode != "exact" and actor is None', source)
        for endpoint in (routes.chemical_substructure, routes.chemical_similarity):
            src = inspect.getsource(endpoint)
            self.assertIn("Depends(internal_or_actor)", src)
            self.assertIn("actor is None", src)

    def test_chemical_reaction_counts_avoid_visible_reaction_point_lookups(self) -> None:
        summary_source = inspect.getsource(routes.reaction_summaries)
        detail_source = inspect.getsource(routes.chemical_detail)
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


if __name__ == "__main__":
    unittest.main()
