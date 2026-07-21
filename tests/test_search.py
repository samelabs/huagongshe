from __future__ import annotations

import os
import unittest

from fastapi import HTTPException

os.environ.setdefault("HGS_DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/test")

from api.routes import bounded_substructure_smiles


class StructureSearchContractTests(unittest.TestCase):
    def test_bounded_substructure_accepts_specific_structure(self) -> None:
        self.assertEqual(bounded_substructure_smiles("c1ccccc1"), "c1ccccc1")

    def test_bounded_substructure_rejects_broad_structure(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            bounded_substructure_smiles("CCO")
        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
