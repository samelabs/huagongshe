from __future__ import annotations

import os
import inspect
import unittest

from fastapi import HTTPException

os.environ.setdefault("HGS_DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/test")

from api.rate_limit import is_loopback_host
from api import routes
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
        self.assertEqual(bounded_substructure_smiles("c1ccccc1"), "c1ccccc1")

    def test_bounded_substructure_rejects_broad_structure(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            bounded_substructure_smiles("CCO")
        self.assertEqual(raised.exception.status_code, 422)

    def test_only_real_loopback_addresses_are_trusted(self) -> None:
        self.assertTrue(is_loopback_host("127.0.0.1"))
        self.assertTrue(is_loopback_host("::1"))
        self.assertFalse(is_loopback_host("127.0.0.1.example.com"))
        self.assertFalse(is_loopback_host("203.0.113.8"))


if __name__ == "__main__":
    unittest.main()
