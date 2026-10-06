"""v1.7.0 Notes / Workbench UI source contracts."""
from __future__ import annotations
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class NotesUiContractTests(unittest.TestCase):
    def test_reference_picker_uses_search_api_without_nested_form_submit(self):
        src = (REPO / "web/components/workbench/EntityReferencePicker.tsx").read_text(encoding="utf-8")
        editor = (REPO / "web/components/workbench/NoteEditor.tsx").read_text(encoding="utf-8")
        self.assertIn("/search?q=", src)
        self.assertIn('type="search"', src)
        self.assertNotIn('type="number"', src)
        self.assertNotIn("<form", src)
        self.assertIn('type="button"', src)
        self.assertIn("onKeyDown=", src)
        self.assertIn("event.preventDefault()", src)
        self.assertEqual(editor.count("<form"), 1)
        self.assertIn("onSubmit={save}", editor)

    def test_note_editor_identity_resets_between_create_and_edit_contexts(self):
        src = (REPO / "web/components/workbench/panels/NotesPanel.tsx").read_text(encoding="utf-8")
        self.assertIn("setEditing(null);", src)
        self.assertIn("`edit-${editing.id}`", src)
        self.assertIn("`new-${initialChemicalId ?? 0}-${initialReactionId ?? 0}-${createOpen ? 1 : 0}`", src)

    def test_mobile_topbar_keeps_creation_actions_without_desktop_duplication(self):
        nav = (REPO / "web/components/workbench/WbTopnav.tsx").read_text(encoding="utf-8")
        css = (REPO / "web/app/(workbench)/aichem.css").read_text(encoding="utf-8")
        self.assertEqual(nav.count('kind: "nav"'), 2)
        self.assertEqual(nav.count('kind: "action"'), 2)
        self.assertIn("aria-label={item.label}", nav)
        self.assertIn(".wb-topnav-link-nav { display: none; }", css)
        self.assertIn(".wb-topbar-user { display: none; }", css)

    def test_reaction_pagination_preserves_workbench_tab(self):
        src = (REPO / "web/components/workbench/panels/ReactionsPanel.tsx").read_text(encoding="utf-8")
        self.assertIn("/aichem?tab=mine", src)

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
