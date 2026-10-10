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
        self.assertIn("latestRequest = useRef(0)", src)
        self.assertIn("requestId !== latestRequest.current", src)
        self.assertEqual(editor.count("<form"), 1)
        self.assertIn("onSubmit={save}", editor)

    def test_note_editor_identity_resets_between_create_and_edit_contexts(self):
        src = (REPO / "web/components/workbench/panels/NotesPanel.tsx").read_text(encoding="utf-8")
        self.assertIn("setEditing(null);", src)
        self.assertIn("setCreateContext({", src)
        self.assertIn("createContext.chemicalIds", src)
        self.assertIn("createContext.reactionIds", src)
        self.assertIn("latestLoad = useRef(0)", src)
        self.assertIn("const created = creating && !editing", src)
        # R3 landing semantics: after save the user must never be stranded on
        # a list where the saved note cannot appear. page 1 + the list can
        # show it (visibility and entity filter both match) → refresh in
        # place; otherwise navigate to the saved note's own visibility list.
        self.assertIn("const visibleHere = visibility === \"all\" || visibility === saved.visibility", src)
        self.assertIn("page === 1 && visibleHere && inFilter", src)
        self.assertIn('params.set("visibility", saved.visibility)', src)
        self.assertIn("redirectIfPageIsEmpty", src)
        self.assertIn("Math.ceil(value.total / value.page_size)", src)
        # normalized landing URL construction (URLSearchParams, not string concat)
        self.assertIn("router.replace(withLocale(`/aichem?${params.toString()}`, locale))", src)

    def test_creation_actions_live_in_sidebar_and_drawer(self):
        """v1.7 Step 5：顶栏统一为全站 SiteHeader 后，工作台顶栏（WbTopnav）删除，
        「新建反应 / 新建笔记」临时安置在侧栏顶部（桌面）与抽屉顶部（手机），
        两处共用 WbQuickActions 单一实现，不与底部 tab 功能重复。"""
        quick = (REPO / "web/components/workbench/WbQuickActions.tsx").read_text(encoding="utf-8")
        layout = (REPO / "web/app/(workbench)/layout.tsx").read_text(encoding="utf-8")
        drawer = (REPO / "web/components/workbench/WbMobileNav.tsx").read_text(encoding="utf-8")
        self.assertIn('variant="primary" size="sm" href={withLocale("/submit"', quick)
        self.assertIn('variant="secondary" size="sm" href={withLocale("/aichem?tab=notes&new=1"', quick)
        self.assertIn("<WbQuickActions />", layout)
        self.assertIn("<WbQuickActions />", drawer)
        self.assertFalse((REPO / "web/components/workbench/WbTopnav.tsx").exists())

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
