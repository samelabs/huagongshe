"""v1.7.0 Notes UI architecture source contracts."""
from __future__ import annotations
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class NotesUiContractTests(unittest.TestCase):
    def test_reference_picker_uses_search_api(self):
        src = (REPO / "web/components/workbench/EntityReferencePicker.tsx").read_text(encoding="utf-8")
        self.assertIn("/search?q=", src)
        self.assertIn('type="search"', src)
        self.assertNotIn('type="number"', src)

    def test_search_pipeline_passes_actor_for_private_hrid_discovery(self):
        src = (REPO / "api/services/search.py").read_text(encoding="utf-8")
        self.assertIn("reaction_lookup(", src)
        self.assertIn("actor_id=actor_id", src)

    def test_entity_pages_embed_generic_notes_component(self):
        chemical = (REPO / "web/app/(site)/chemical/[id]/page.tsx").read_text(encoding="utf-8")
        reaction = (REPO / "web/app/(site)/reaction/[id]/page.tsx").read_text(encoding="utf-8")
        self.assertIn('<EntityNotes entity="chemical"', chemical)
        self.assertIn('<EntityNotes entity="reaction"', reaction)

    def test_notes_panel_stays_independent(self):
        src = (REPO / "web/components/workbench/panels/NotesPanel.tsx").read_text(encoding="utf-8")
        for forbidden in ("ReactionsPanel", "SavedPanel", "ActivityPanel"):
            self.assertNotIn(forbidden, src)

    def test_home_orders_notes_before_reactions(self):
        src = (REPO / "web/components/workbench/panels/HomePanel.tsx").read_text(encoding="utf-8")
        self.assertLess(src.index("homeRecentNotes"), src.index("homeRecentReactions"))

    def test_workspace_order_matches_product_ia(self):
        src = (REPO / "web/components/workbench/registry.ts").read_text(encoding="utf-8")
        positions = [
            src.index('{ id: "home",        section: "workspace"'),
            src.index('{ id: "notes",       section: "workspace"'),
            src.index('{ id: "mine",        section: "workspace"'),
            src.index('{ id: "saved",       section: "workspace"'),
        ]
        self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()
