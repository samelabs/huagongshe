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

    def test_creation_actions_live_in_drawer_and_overview(self):
        """v1.7 Step 8 §9.4：桌面侧栏不再放「新建反应 / 新建笔记」（概览标题行
        承担创建入口），手机抽屉顶部保留一份（WbQuickActions 单一实现），
        不与底部 tab 功能重复。"""
        quick = (REPO / "web/components/workbench/WbQuickActions.tsx").read_text(encoding="utf-8")
        layout = (REPO / "web/app/(workbench)/layout.tsx").read_text(encoding="utf-8")
        drawer = (REPO / "web/components/workbench/WbMobileNav.tsx").read_text(encoding="utf-8")
        self.assertIn('variant="primary" size="sm" href={withLocale("/submit"', quick)
        self.assertIn('variant="secondary" size="sm" href={withLocale("/aichem?tab=notes&new=1"', quick)
        self.assertNotIn("<WbQuickActions />", layout)
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

    def test_home_overview_carries_create_actions(self):
        """Step 8 §9.4：桌面创建入口 = 概览标题行（新建笔记 secondary +
        新建反应 primary）；手机收进顶栏「+」菜单（WbCreateMenu）。"""
        home = (REPO / "web/components/workbench/panels/HomePanel.tsx").read_text(encoding="utf-8")
        self.assertIn('href={withLocale("/aichem?tab=notes&new=1", locale)}>{t.me.navNewNote}', home)
        self.assertIn('href={withLocale("/submit", locale)}>{t.me.navNewReaction}', home)
        menu = (REPO / "web/components/workbench/WbCreateMenu.tsx").read_text(encoding="utf-8")
        self.assertIn('href={withLocale("/submit", locale)}', menu)
        self.assertIn('href={withLocale("/aichem?tab=notes&new=1", locale)}', menu)

    def test_home_recent_merges_three_streams(self):
        """Step 8 §9.4 概览「最近」：反应/笔记/收藏按时间合并取前 8，
        全部走既有读接口（SSR 预取）。"""
        home = (REPO / "web/components/workbench/panels/HomePanel.tsx").read_text(encoding="utf-8")
        self.assertIn(".slice(0, 8)", home)
        self.assertIn("sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime())", home)
        page = (REPO / "web/app/(workbench)/aichem/page.tsx").read_text(encoding="utf-8")
        self.assertIn("/users/me/notes?visibility=all&page=1&page_size=8", page)
        self.assertIn("/users/me/reactions?visibility=all&page=1&page_size=8", page)
        self.assertIn("/users/me/follows/chemicals?page=1&page_size=8", page)
        self.assertIn("/users/me/notifications?page=1&page_size=5", page)
        # 旧版三统计卡与「连接 AI 助手」大提示框删除（入口收进快捷入口）
        self.assertNotIn("wb-home-stats", home)
        self.assertNotIn("wb-home-guide", home)
        css = (REPO / "web/app/(workbench)/aichem.css").read_text(encoding="utf-8")
        self.assertNotIn(".wb-home-stats", css)
        self.assertNotIn(".wb-home-guide", css)

    def test_workspace_order_matches_product_ia(self):
        """Step 8 §9.4：registry 分组收敛为 workspace/tools/network/account 四组
        （agent 并入 tools，api-tokens 移入 tools 作「MCP 与 AI Key」，账户只留
        设置）。id 与 href 不变（深链/测试钉子稳定），只动展示分组与图标。"""
        src = (REPO / "web/components/workbench/registry.ts").read_text(encoding="utf-8")
        positions = [
            src.index('{ id: "home",'),
            src.index('{ id: "notes",'),
            src.index('{ id: "mine",'),
            src.index('{ id: "saved",'),
            src.index('{ id: "search",'),
            src.index('{ id: "stoich",'),
            src.index('{ id: "skills",'),
            src.index('{ id: "api-tokens",'),
            src.index('{ id: "activity",'),
            src.index('{ id: "following",'),
            src.index('{ id: "followers",'),
            src.index('{ id: "profile",'),
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('section: "workspace"', src)
        self.assertIn('section: "tools"', src)
        self.assertIn('section: "network"', src)
        self.assertIn('section: "account"', src)
        self.assertNotIn('section: "agent"', src)
        # 深链稳定：id 与 href 组合不被分组调整改写
        self.assertIn('{ id: "api-tokens", section: "tools",     href: "/me/settings/api-tokens"', src)
        self.assertIn('{ id: "profile",    section: "account",   href: "/me/settings/profile"', src)
        # 侧栏「笔记」计数来自 Counts.notes（layout 用 notes?page_size=1 补齐）
        self.assertIn('badge: (c) => c.notes', src)
        self.assertIn("/users/me/notes?page=1&page_size=1",
                      (REPO / "web/app/(workbench)/layout.tsx").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
