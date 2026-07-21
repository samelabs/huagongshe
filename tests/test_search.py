from __future__ import annotations

import os
import inspect
import unittest

from fastapi import HTTPException

os.environ.setdefault("HGS_DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/test")

from api.rate_limit import is_loopback_host
from api import routes
from api.routes import bounded_substructure_smiles


class StructureSearchContractTests(unittest.TestCase):
    def test_exact_search_is_not_cached_with_mutable_user_reactions(self) -> None:
        source = inspect.getsource(routes.search)
        self.assertEqual(source.count('if mode != "exact":'), 2)

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
