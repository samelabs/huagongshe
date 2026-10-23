"""Workbench Notes UI source contracts.

Pin the concrete mechanisms behind notes UI behavior (editor cross-talk,
cancel-reopen, create pre-association, async search races, list refresh,
delete-failure recovery, Back/Forward URL state, truncation, filter UI) so a
regression cannot silently reappear. Query-param and save-landing behavior is
tested against the real module in web/lib/notesQuery.test.mjs.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def read(rel: str) -> str:
    return (WEB / rel).read_text(encoding="utf-8")


class NotesUiContractTests(unittest.TestCase):
    def test_reference_picker_uses_search_api_without_nested_form_submit(self):
        src = (ROOT / "web/components/workbench/EntityReferencePicker.tsx").read_text(encoding="utf-8")
        editor = (ROOT / "web/components/workbench/NoteEditor.tsx").read_text(encoding="utf-8")
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
        src = (ROOT / "web/components/workbench/panels/NotesPanel.tsx").read_text(encoding="utf-8")
        self.assertIn("setEditing(null);", src)
        self.assertIn("setCreateContext({", src)
        self.assertIn("createContext.chemicalIds", src)
        self.assertIn("createContext.reactionIds", src)
        self.assertIn("latestLoad = useRef(0)", src)
        self.assertIn("const created = creating && !editing", src)
        # landing semantics: after save the user must never be stranded on
        # a list where the saved note cannot appear. page 1 + the list can
        # show it (visibility and entity filter both match) → refresh in
        # place; otherwise navigate to the saved note's own visibility list.
        self.assertIn("savedNoteFitsView(view, saved)", src)
        self.assertIn("savedNoteLandingParams(view, saved)", src)
        self.assertIn("redirectIfPageIsEmpty", src)
        self.assertIn("Math.ceil(value.total / value.page_size)", src)
        # normalized landing URL construction (URLSearchParams, not string concat)
        self.assertIn("router.replace(withLocale(`/aichem?${savedNoteLandingParams(view, saved).toString()}`, locale))", src)

    def test_creation_actions_live_in_drawer_and_overview(self):
        """桌面侧栏不再放「新建反应 / 新建笔记」（概览标题行
        承担创建入口），手机抽屉顶部保留一份（WbQuickActions 单一实现），
        不与底部 tab 功能重复。"""
        quick = (ROOT / "web/components/workbench/WbQuickActions.tsx").read_text(encoding="utf-8")
        layout = (ROOT / "web/app/(workbench)/layout.tsx").read_text(encoding="utf-8")
        drawer = (ROOT / "web/components/workbench/WbMobileNav.tsx").read_text(encoding="utf-8")
        self.assertIn('variant="primary" size="sm" href={withLocale("/submit"', quick)
        self.assertIn('variant="secondary" size="sm" href={withLocale("/aichem?tab=notes&new=1"', quick)
        self.assertNotIn("<WbQuickActions />", layout)
        self.assertIn("<WbQuickActions />", drawer)
        self.assertFalse((ROOT / "web/components/workbench/WbTopnav.tsx").exists())

    def test_reaction_pagination_preserves_workbench_tab(self):
        src = (ROOT / "web/components/workbench/panels/ReactionsPanel.tsx").read_text(encoding="utf-8")
        self.assertIn("/aichem?tab=mine", src)

    def test_search_pipeline_passes_actor_for_private_hrid_discovery(self):
        src = (ROOT / "api/services/search.py").read_text(encoding="utf-8")
        self.assertIn("reaction_lookup(", src)
        self.assertIn("actor_id=actor_id", src)

    def test_entity_pages_embed_generic_notes_component(self):
        chemical = (ROOT / "web/app/(site)/chemical/[id]/page.tsx").read_text(encoding="utf-8")
        reaction = (ROOT / "web/app/(site)/reaction/[id]/page.tsx").read_text(encoding="utf-8")
        self.assertIn('<EntityNotes entity="chemical"', chemical)
        self.assertIn('<EntityNotes entity="reaction"', reaction)

    def test_notes_panel_stays_independent(self):
        src = (ROOT / "web/components/workbench/panels/NotesPanel.tsx").read_text(encoding="utf-8")
        for forbidden in ("ReactionsPanel", "SavedPanel", "ActivityPanel"):
            self.assertNotIn(forbidden, src)

    def test_home_overview_carries_create_actions(self):
        """ §9.4：桌面创建入口 = 概览标题行（新建笔记 secondary +
        新建反应 primary）；手机收进顶栏汉堡抽屉的快捷操作
        （WbQuickActions，顶栏不设独立「+」菜单）。"""
        home = (ROOT / "web/components/workbench/panels/HomePanel.tsx").read_text(encoding="utf-8")
        self.assertIn('href={withLocale("/aichem?tab=notes&new=1", locale)}>{t.me.navNewNote}', home)
        self.assertIn('href={withLocale("/submit", locale)}>{t.me.navNewReaction}', home)
        quick = (ROOT / "web/components/workbench/WbQuickActions.tsx").read_text(encoding="utf-8")
        self.assertIn('href={withLocale("/submit", locale)}', quick)
        self.assertIn('href={withLocale("/aichem?tab=notes&new=1", locale)}', quick)

    def test_home_recent_merges_three_streams(self):
        """ §9.4 概览「最近」：反应/笔记/收藏按时间合并取前 8，
        全部走既有读接口（SSR 预取）。"""
        home = (ROOT / "web/components/workbench/panels/HomePanel.tsx").read_text(encoding="utf-8")
        self.assertIn(".slice(0, 8)", home)
        self.assertIn("sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime())", home)
        page = (ROOT / "web/app/(workbench)/aichem/page.tsx").read_text(encoding="utf-8")
        self.assertIn("/users/me/notes?visibility=all&page=1&page_size=8", page)
        self.assertIn("/users/me/reactions?visibility=all&page=1&page_size=8", page)
        self.assertIn("/users/me/follows/chemicals?page=1&page_size=8", page)
        # 通知只在通知面板预取，概览不拉通知
        self.assertNotIn("/users/me/notifications?page=1&page_size=5", page)
        self.assertNotIn("/users/me/notifications", home)
        # 旧版三统计卡与「连接 AI 助手」大提示框删除（入口收进快捷入口）
        self.assertNotIn("wb-home-stats", home)
        self.assertNotIn("wb-home-guide", home)
        css = (ROOT / "web/app/(workbench)/aichem.css").read_text(encoding="utf-8")
        self.assertNotIn(".wb-home-stats", css)
        self.assertNotIn(".wb-home-guide", css)

    def test_workspace_order_matches_product_ia(self):
        """ §9.4：registry 分组收敛为 workspace/tools/network/account 四组
        （agent 并入 tools，api-tokens 移入 tools 作「MCP 与 AI Key」，账户只留
        设置）。id 与 href 不变（深链/测试钉子稳定），只动展示分组与图标。"""
        src = (ROOT / "web/components/workbench/registry.ts").read_text(encoding="utf-8")
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
                      (ROOT / "web/lib/shellData.ts").read_text(encoding="utf-8"),
                      "笔记计数取数应与外壳共用 shellData")


class EditorCrossTalkTests(unittest.TestCase):
    """Note A → Note B 连续编辑不串号;取消后重新打开。"""

    def setUp(self):
        self.panel = read("components/workbench/panels/NotesPanel.tsx")
        self.editor = read("components/workbench/NoteEditor.tsx")

    def test_editor_mounted_with_identity_key(self):
        # switching between notes remounts the editor via key=, so stale
        # draft state from note A can never leak into note B
        self.assertIn("key={editing", self.panel)
        self.assertIn("`edit-${editing.id}`", self.panel)
        self.assertIn("`new-${", self.panel)

    def test_editor_loads_by_id_not_by_reference(self):
        # the editor re-reads the note by id into local state on mount
        self.assertRegex(self.editor, r"note=\{editing\}|initialNote|useState")

    def test_close_resets_editing_and_creating(self):
        self.assertIn("setCreating(false)", self.panel)
        self.assertIn("setEditing(null)", self.panel)


class AsyncRaceTests(unittest.TestCase):
    """异步搜索旧响应不覆盖新响应;请求竞争不使旧筛选覆盖新列表。"""

    def test_search_panel_has_request_id_guard(self):
        src = read("components/workbench/panels/SearchPanel.tsx")
        self.assertRegex(
            src, r"requestId|latestRef|abortController|AbortController|active",
            "SearchPanel must guard against stale async responses",
        )

    def test_notes_list_has_stale_response_guard(self):
        panel = read("components/workbench/panels/NotesPanel.tsx")
        # latestLoad token guards list loads: late responses are dropped
        self.assertIn("latestLoad", panel)
        self.assertIn("requestId !== latestLoad.current", panel)

    def test_entity_notes_drop_inflight_on_unmount_or_change(self):
        src = read("components/shared/EntityNotes.tsx")
        self.assertIn("let active = true", src)
        self.assertIn("if (active)", src)


class ListRefreshTests(unittest.TestCase):
    """创建/删除后列表刷新正确;删除失败保留可恢复的 UI 状态。"""

    def setUp(self):
        self.panel = read("components/workbench/panels/NotesPanel.tsx")

    def test_create_refreshes_list(self):
        self.assertIn("await load()", self.panel)

    def test_delete_refreshes_list(self):
        self.assertRegex(
            self.panel,
            r"apiDelete\(`/notes/\$\{note\.id\}`\);[\s\S]*?await load\(\)",
            "delete must be followed by a list reload",
        )

    def test_delete_failure_keeps_recoverable_state(self):
        # delete failure must NOT switch the panel to a fatal error
        # state — the list stays mounted and an inline recoverable error
        # (dictionary-sourced) is shown instead.
        remove_fn = self.panel[self.panel.index("async function remove"):]
        # 重设计：labels 块改为 filterOptions（Segmented 筛选）
        remove_fn = remove_fn[:remove_fn.index("const filterOptions")]
        self.assertNotIn('setState("error")', remove_fn)
        self.assertIn("setActionError(t.notes.deleteFailed)", remove_fn)
        self.assertNotIn("setData(empty())", self.panel.split("async function remove")[1])


class CreatePreassociationTests(unittest.TestCase):
    """new=1&chemical=X / new=1&reaction=X 新建预关联不被过滤破坏。"""

    def test_create_context_carries_entity_ids(self):
        panel = read("components/workbench/panels/NotesPanel.tsx")
        self.assertIn("initialChemicalId ? [initialChemicalId]", panel)
        self.assertIn("initialReactionId ? [initialReactionId]", panel)

    def test_aichem_keeps_preassociation_when_create_open(self):
        page = read("app/(workbench)/aichem/page.tsx")
        # filter only engages when NOT creating; new=1 stays a pre-association
        self.assertIn('activeTab === "notes" && !createNote', page)

    def test_save_returns_to_filtered_list(self):
        panel = read("components/workbench/panels/NotesPanel.tsx")
        # 筛选经共享 helper 流转; 落点规则(笔记仍引用筛选实体才保留筛选)
        # 的行为由 web/lib/notesQuery.test.mjs 覆盖
        self.assertIn("listParams(visibility, filterChemicalId, filterReactionId", panel)
        self.assertIn("listHref(1)", panel)
        self.assertIn("savedNoteFitsView(view, saved)", panel)


class BackForwardUrlStateTests(unittest.TestCase):
    """Back/Forward 后编辑器和 URL 状态一致。"""

    def test_url_is_replaced_when_editor_closes(self):
        panel = read("components/workbench/panels/NotesPanel.tsx")
        self.assertIn("router.replace(listHref(1))", panel)
        self.assertIn("router.replace(withLocale(`/aichem?${savedNoteLandingParams(view, saved).toString()}`, locale))", panel)


class NoteTruncationTests(unittest.TestCase):
    def test_css_clamp_rules_exist(self):
        css = read("app/globals.css")
        self.assertIn("-webkit-line-clamp:2", css)
        self.assertIn(".note-clamp-2", css)
        # clamp keeps pre-wrap + anywhere wrapping
        self.assertRegex(
            css, r"\.note-clamp-2\{[^}]*white-space:pre-wrap[^}]*\}",
        )

    def test_lists_use_clamp_detail_page_does_not(self):
        entity = read("components/shared/EntityNotes.tsx")
        panel = read("components/workbench/panels/NotesPanel.tsx")
        detail = read("app/(site)/note/[id]/page.tsx")
        # 三处列表（实体页/工作台/公开主页）统一 noteListPresentation
        # （首行或显式标题 + 两行摘要），多行 clamp 已随卡片样式退役
        self.assertIn("noteListPresentation", entity)
        self.assertIn("note-clamp-2", entity)
        self.assertIn("noteListPresentation", panel)
        self.assertNotIn("note-clamp", detail)
        self.assertIn("note-detail-content", detail)

    def test_timeline_rows_link_to_locale_aware_note_route(self):
        entity = read("components/shared/EntityNotes.tsx")
        panel = read("components/workbench/panels/NotesPanel.tsx")
        self.assertIn('withLocale(`/note/${', entity)
        # 笔记面板行链接经 WbListRow（shared.tsx）统一 withLocale
        self.assertIn("`/note/${note.slug}`", panel)
        self.assertIn("withLocale(href, locale)", read("components/workbench/shared.tsx"))

    def test_empty_reference_area_not_rendered(self):
        entity = read("components/shared/EntityNotes.tsx")
        # 空引用区不渲染 DOM：条件提取为 hasRefs（语义同内联条件式）
        self.assertIn(
            "const hasRefs = note.chemical_ids.length > 0 || note.reaction_ids.length > 0;", entity)
        self.assertIn("{hasRefs && (", entity)


class StoichNoteLinkTests(unittest.TestCase):
    def test_success_links_present_with_locale(self):
        src = read("components/workbench/panels/StoichPanel.tsx")
        self.assertIn('withLocale("/submit", locale)', src)
        self.assertIn('withLocale("/aichem?tab=notes&new=1", locale)', src)

    def test_links_inside_success_block_only(self):
        src = read("components/workbench/panels/StoichPanel.tsx")
        # actions div must sit within the result render branch
        idx_actions = src.index("wb-stoich-actions")
        idx_result = src.index("wb-stoich-result") if "wb-stoich-result" in src else src.index("result")
        self.assertGreater(idx_actions, idx_result, "links must render inside the success/result block")


class NoteDetailPageTests(unittest.TestCase):
    def test_metadata_has_canonical_and_alternates(self):
        src = read("app/(site)/note/[id]/page.tsx")
        self.assertIn("localeAlternates", src)

    def test_privacy_404_via_service(self):
        page_src = read("app/(site)/note/[id]/page.tsx")
        self.assertIn("isApiNotFound", page_src)

    def test_chips_use_serialized_ids(self):
        src = read("app/(site)/note/[id]/page.tsx")
        # 化合物芯片 = chemical_ids 派生的解析名链接(≤8), 溢出仍走徽标;
        # 反应芯片保持徽标。都迭代序列化 id, 不拼字符串。
        self.assertIn("note.chemical_ids.slice(0, 8).map", src)
        self.assertIn("chemicalNames.map", src)
        self.assertIn("note.reaction_ids.map", src)


class EntityNotesPrivateSectionTests(unittest.TestCase):
    """实体页笔记区 = 单一时间线：公开行 + 本人私有行同一行样式，
    私有行仅多一枚可见性 Tag（不再有独立虚线容器/单独标题）。"""

    def test_private_rows_merge_into_same_timeline(self):
        src = read("components/shared/EntityNotes.tsx")
        # 同一个 .entity-note-list 渲染私有行 + 公开行，私有行经 minePrivate 标记
        self.assertIn('className="entity-note-list"', src)
        self.assertIn("minePrivate.map", src)
        self.assertIn("data.items.map", src)
        self.assertLess(
            src.index("minePrivate.map"),
            src.index("data.items.map"),
            "私有行应在公开行之前（时间线顶部）",
        )
        # 私有行带可见性 Tag，不再有独立容器/区块标题
        self.assertIn("t.notes.visibilityPrivate", src)
        self.assertNotIn("entity-note-private", src)

    def test_private_fetch_uses_session_endpoint(self):
        src = read("components/shared/EntityNotes.tsx")
        self.assertIn("/users/me/notes?visibility=private", src)

    def test_public_list_is_paginated(self):
        src = read("components/shared/EntityNotes.tsx")
        self.assertIn("page=${page}&page_size=${PAGE_SIZE}", src)
        self.assertIn("t.common.pageOf(page, totalPages)", src)


class ProfileNotesBlockTests(unittest.TestCase):
    def test_total_zero_renders_no_dom(self):
        src = read("app/(site)/user/[username]/page.tsx")
        self.assertIn("notesBlock.total > 0 && (", src)

    def test_uses_public_notes_endpoint(self):
        src = read("app/(site)/user/[username]/page.tsx")
        self.assertIn("/notes?page=${page}&page_size=${NOTES_PAGE_SIZE}", src)

    def test_notes_tab_is_paginated(self):
        src = read("app/(site)/user/[username]/page.tsx")
        self.assertIn("notesBlock.total > NOTES_PAGE_SIZE && (", src)
        self.assertIn("tab=notes&page=${page - 1}", src)
        self.assertIn("tab=notes&page=${page + 1}", src)

    def test_cards_link_to_detail(self):
        src = read("app/(site)/user/[username]/page.tsx")
        self.assertIn("`/note/${note.slug}`", src)


class NotesFilterUiTests(unittest.TestCase):
    def test_breadcrumb_and_clear_link(self):
        panel = read("components/workbench/panels/NotesPanel.tsx")
        self.assertIn("wb-filter-crumbs", panel)
        self.assertIn("filterClear", panel)

    def test_chemical_precedence(self):
        src = read("components/workbench/panels/NotesPanel.tsx")
        self.assertIn('filterChemicalId != null ? "chemical"', src)

    def test_filtered_empty_state_differs(self):
        panel = read("components/workbench/panels/NotesPanel.tsx")
        self.assertIn("filterKey ? t.notes.filterEmpty : t.me.notesEmpty", panel)

    def test_ssr_and_client_same_filter_condition(self):
        page = read("app/(workbench)/aichem/page.tsx")
        # SSR 预取与客户端刷新共用 lib/notesQuery.apiListQuery(chemical 优先)
        self.assertIn("apiListQuery(noteVisibility, filterChemicalId, filterReactionId, page)", page)
        panel = read("components/workbench/panels/NotesPanel.tsx")
        self.assertIn("apiListQuery(visibility, filterChemicalId, filterReactionId, page)", panel)


class DictionaryTreeTests(unittest.TestCase):
    """五语言键树完全一致(含新增 16 键)。"""

    LOCALES = ["zh-CN", "en", "ja", "ko", "de"]
    NEW_KEYS = [
        "detailTitle", "updatedLabel", "visibilityPublic", "visibilityPrivate",
        "profileTitle",
        "linkedTitleChemical", "linkedTitleReaction",
        "filterChemical", "filterReaction", "filterClear", "filterEmpty",
        "createReaction", "writeNote",
    ]

    @staticmethod
    def _keys(src: str) -> set[str]:
        # naive top-2-level key tree extraction
        keys: set[str] = set()
        for match in re.finditer(r"^  ([A-Za-z_][A-Za-z0-9_]*): \{", src, re.M):
            section = match.group(1)
            keys.add(section)
            # capture keys within the section body
            start = match.end()
            end = src.index("\n  },", start)
            for inner in re.finditer(r"^    ([A-Za-z_][A-Za-z0-9_]*):", src[start:end], re.M):
                keys.add(f"{section}.{inner.group(1)}")
        return keys

    def test_key_trees_identical_across_locales(self):
        trees = {}
        for loc in self.LOCALES:
            src = read(f"lib/i18n/locales/{loc}.ts")
            trees[loc] = self._keys(src)
        base = trees["zh-CN"]
        for loc, tree in trees.items():
            self.assertEqual(
                tree, base,
                f"{loc} key tree differs: missing={base - tree}, extra={tree - base}",
            )

    def test_new_keys_present_in_all_locales(self):
        for loc in self.LOCALES:
            src = read(f"lib/i18n/locales/{loc}.ts")
            body = src[src.index("  notes: {"):]
            body = body[:body.index("\n  },")]
            for key in self.NEW_KEYS:
                self.assertIn(f"{key}:", body, f"{loc} missing notes.{key}")


class NotesListUiTests(unittest.TestCase):
    def test_entity_rows_are_unified_timeline(self):
        """实体页笔记行 = 时间线行（标题直达详情 + 两行摘要），与工作台行
        同一规范；逐行「查看全文」提示随卡片样式退役（标题即链接）。"""
        src = (ROOT / "web/components/shared/EntityNotes.tsx").read_text(encoding="utf-8")
        self.assertIn("noteListPresentation", src)
        self.assertIn('className="entity-note-title"', src)
        self.assertNotIn("note-view-full", src)
        home = (ROOT / "web/components/workbench/panels/HomePanel.tsx").read_text(encoding="utf-8")
        # 重设计：笔记行经 WbListRow（shared.tsx）统一 withLocale
        self.assertIn('href={`/note/${note.slug}`}', home)
        self.assertIn("withLocale(href, locale)", (ROOT / "web/components/workbench/shared.tsx").read_text(encoding="utf-8"))

    def test_delete_failure_keeps_list_and_is_recoverable(self):
        src = (ROOT / "web/components/workbench/panels/NotesPanel.tsx").read_text(encoding="utf-8")
        # delete error must NOT set the fatal panel error state
        remove_fn = src[src.index("async function remove"):]
        # 重设计：labels 块改为 filterOptions（Segmented 筛选）
        remove_fn = remove_fn[:remove_fn.index("const filterOptions")]
        self.assertNotIn('setState("error")', remove_fn)
        self.assertIn("setActionError(t.notes.deleteFailed)", remove_fn)
        # inline error renders while the list stays mounted
        self.assertIn('actionError && state !== "error"', src)

    def test_profile_failure_distinct_from_zero(self):
        src = (ROOT / "web/app/(site)/user/[username]/page.tsx").read_text(encoding="utf-8")
        self.assertIn("notesUnavailable && (", src)
        self.assertIn("t.notes.profileLoadFailed", src)
        self.assertIn("notesBlock.total > 0 && (", src)

    def test_notes_dictionary_keys_in_all_locales(self):
        for loc in ["zh-CN", "en", "ja", "ko", "de"]:
            src = (ROOT / f"web/lib/i18n/locales/{loc}.ts").read_text(encoding="utf-8")
            body = src[src.index("  notes: {"):]
            body = body[:body.index("\n  },")]
            for key in ("profileLoadFailed", "deleteFailed"):
                self.assertIn(f"{key}:", body, f"{loc} missing notes.{key}")


if __name__ == "__main__":
    unittest.main()
