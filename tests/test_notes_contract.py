"""v1.7.0 Notes contract tests that do not require a database."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from pydantic import ValidationError

from api.schemas.notes import MAX_NOTE_REFERENCES, NoteBody
from api.services.identity import CHEMICAL_REFERENCE_TABLES

REPO = Path(__file__).resolve().parents[1]


class NoteSchemaTests(unittest.TestCase):
    def test_reference_ids_are_deduplicated_preserving_order(self):
        body = NoteBody(
            content="  observation  ",
            chemical_ids=[5, 5, 3],
            reaction_ids=[9, 9],
        )
        self.assertEqual(body.content, "observation")
        self.assertEqual(body.chemical_ids, [5, 3])
        self.assertEqual(body.reaction_ids, [9])

    def test_empty_or_over_limit_is_rejected(self):
        with self.assertRaises(ValidationError):
            NoteBody(content="   ")
        with self.assertRaises(ValidationError):
            NoteBody(
                content="x",
                chemical_ids=list(range(1, MAX_NOTE_REFERENCES + 2)),
            )

    def test_non_positive_reference_is_rejected(self):
        with self.assertRaises(ValidationError):
            NoteBody(content="x", chemical_ids=[0])


class NoteArchitectureTests(unittest.TestCase):
    def test_service_is_transport_neutral(self):
        tree = ast.parse((REPO / "api/services/notes.py").read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        self.assertFalse(any(name.startswith("fastapi") for name in imports))
        self.assertFalse(any(name.startswith("mcp") for name in imports))

    def test_note_chemical_reference_is_identity_registered(self):
        rows = {
            (schema, table): cfg
            for schema, table, cfg in CHEMICAL_REFERENCE_TABLES
        }
        cfg = rows[("community", "note_chemicals")]
        self.assertEqual(cfg["strategy"], "DEDUPE_REKEY")
        self.assertEqual(tuple(cfg["dedupe_key"]), ("note_id",))
        self.assertEqual(tuple(cfg["merge_cols"]), ())

    def test_note_routes_require_session_for_mutations(self):
        src = (REPO / "api/notes.py").read_text(encoding="utf-8")
        for name in ("create_note", "update_note", "delete_note"):
            segment = src.split(f"async def {name}", 1)[1].split("\n\n@router.", 1)[0]
            self.assertIn("Depends(current_session)", segment, name)
        self.assertNotIn("require_scope", src, "v1.7.0 Notes Web CRUD must not create an agent scope")

    def test_reaction_note_field_is_not_repurposed(self):
        src = (REPO / "api/services/notes.py").read_text(encoding="utf-8")
        self.assertNotIn("chemistry.reactions SET note", src)
        self.assertNotIn("UPDATE chemistry.reactions", src)


if __name__ == "__main__":
    unittest.main()
