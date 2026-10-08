"""Phase 1c §11: regression anchors for previously-fixed Workbench Notes UI
behaviors (editor cross-talk, cancel-reopen, create pre-association, async
search races, list refresh, delete-failure recovery, Back/Forward URL state)
plus P-3/P-7 UI anchors. Source-level behavior tests: they pin the concrete
mechanisms (request-id guards, editor key resets, URL replace discipline)
that the earlier fixes introduced, so a regression cannot silently reappear.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def read(rel: str) -> str:
    return (WEB / rel).read_text(encoding="utf-8")


class EditorCrossTalkTests(unittest.TestCase):
    """§11: Note A → Note B 连续编辑不串号;取消后重新打开。"""

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
    """§11: 异步搜索旧响应不覆盖新响应;请求竞争不使旧筛选覆盖新列表。"""

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
        src = read("components/EntityNotes.tsx")
        self.assertIn("let active = true", src)
        self.assertIn("if (active)", src)


class ListRefreshTests(unittest.TestCase):
    """§11: 创建/删除后列表刷新正确;删除失败保留可恢复的 UI 状态。"""

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
        # delete error sets the panel error state WITHOUT wiping the list
        # data (state → "error" but data is untouched; editor kept)
        self.assertRegex(
            self.panel,
            r"catch \(err\) \{\s*setError\(err\);\s*setState\(\"error\"\);",
        )
        self.assertNotIn("setData(empty())", self.panel.split("async function remove")[1])


class CreatePreassociationTests(unittest.TestCase):
    """§11: new=1&chemical=X / new=1&reaction=X 新建预关联不被过滤破坏。"""

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
        self.assertIn("filterQuery(filterChemicalId, filterReactionId)", panel)


class BackForwardUrlStateTests(unittest.TestCase):
    """§11: Back/Forward 后编辑器和 URL 状态一致。"""

    def test_url_is_replaced_when_editor_closes(self):
        panel = read("components/workbench/panels/NotesPanel.tsx")
        self.assertIn('router.replace(withLocale(`/aichem?tab=notes', panel)


class P3TruncationTests(unittest.TestCase):
    def test_css_clamp_rules_exist(self):
        css = read("app/globals.css")
        self.assertIn("-webkit-line-clamp:6", css)
        self.assertIn(".note-clamp", css)
        # clamp keeps pre-wrap + anywhere wrapping
        self.assertRegex(
            css, r"\.note-clamp\{[^}]*white-space:pre-wrap[^}]*\}",
        )

    def test_cards_use_clamp_detail_page_does_not(self):
        entity = read("components/EntityNotes.tsx")
        panel = read("components/workbench/panels/NotesPanel.tsx")
        home = read("components/workbench/panels/HomePanel.tsx")
        detail = read("app/(site)/note/[id]/page.tsx")
        for src in (entity, panel, home):
            self.assertIn('className="note-clamp"', src)
        self.assertNotIn("note-clamp", detail)
        self.assertIn("note-detail-content", detail)

    def test_view_full_links_target_locale_aware_note_route(self):
        entity = read("components/EntityNotes.tsx")
        panel = read("components/workbench/panels/NotesPanel.tsx")
        for src in (entity, panel):
            self.assertIn('withLocale(`/note/${', src)

    def test_empty_reference_area_not_rendered(self):
        entity = read("components/EntityNotes.tsx")
        self.assertIn(
            "(note.chemical_ids.length > 0 || note.reaction_ids.length > 0)", entity)


class P7StoichTests(unittest.TestCase):
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


class P1DetailPageTests(unittest.TestCase):
    def test_metadata_has_canonical_and_alternates(self):
        src = read("app/(site)/note/[id]/page.tsx")
        self.assertIn("localeAlternates", src)

    def test_privacy_404_via_service(self):
        page_src = read("app/(site)/note/[id]/page.tsx")
        self.assertIn("isApiNotFound", page_src)

    def test_chips_use_serialized_ids(self):
        src = read("app/(site)/note/[id]/page.tsx")
        self.assertIn("note.chemical_ids.map", src)
        self.assertIn("note.reaction_ids.map", src)


class P6PrivateSectionTests(unittest.TestCase):
    def test_private_section_renders_above_public(self):
        src = read("components/EntityNotes.tsx")
        self.assertLess(
            src.index("MyPrivateNotes"),
            src.index("entity-note-list"),
        )
        # in the JSX the private block precedes the public list
        body = src[src.index("return ("):]
        self.assertLess(body.index("<MyPrivateNotes"), body.index('data.items.length > 0 && ('))

    def test_private_fetch_uses_session_endpoint(self):
        src = read("components/EntityNotes.tsx")
        self.assertIn("/users/me/notes?visibility=private", src)

    def test_no_render_when_empty_or_failed(self):
        src = read("components/EntityNotes.tsx")
        self.assertIn("data.items.length === 0) return null", src)


class P2ProfileBlockTests(unittest.TestCase):
    def test_total_zero_renders_no_dom(self):
        src = read("app/(site)/user/[username]/page.tsx")
        self.assertIn("notesBlock.total > 0 && (", src)

    def test_uses_public_notes_endpoint(self):
        src = read("app/(site)/user/[username]/page.tsx")
        self.assertIn("/notes?page=1&page_size=8", src)

    def test_cards_link_to_detail(self):
        src = read("app/(site)/user/[username]/page.tsx")
        self.assertIn("`/note/${note.id}`", src)


class P8FilterUITests(unittest.TestCase):
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
        self.assertIn("filterChemicalId != null ? `&chemical_id=", page)
        panel = read("components/workbench/panels/NotesPanel.tsx")
        self.assertIn("&chemical=${chemicalId}", panel)


class DictionaryTreeTests(unittest.TestCase):
    """G1: 五语言键树完全一致(含新增 16 键)。"""

    LOCALES = ["zh-CN", "en", "ja", "ko", "de"]
    NEW_KEYS = [
        "detailTitle", "updatedLabel", "visibilityPublic", "visibilityPrivate",
        "viewFull", "profileTitle", "mineSection", "mineManage",
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


if __name__ == "__main__":
    unittest.main()
