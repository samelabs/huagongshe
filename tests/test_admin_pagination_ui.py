"""Admin 分页源码契约: 共享 AdminPagination 组件与 users/reactions/skills
三面板的 URL 状态与 offset 换算。分页纯函数的行为测试在
web/lib/adminPagination.test.mjs。
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def read(p: str) -> str:
    return (WEB / p).read_text(encoding="utf-8")


class AdminPaginationComponentTests(unittest.TestCase):
    def setUp(self):
        self.src = read("components/samelabs/AdminPagination.tsx")

    def test_first_page_prev_disabled(self):
        self.assertIn("disabled={page <= 1", self.src)

    def test_last_page_next_disabled(self):
        self.assertIn("disabled={page >= totalPages", self.src)

    def test_meta_shows_page_and_total(self):
        self.assertIn("第 {page} / {totalPages} 页 · 共 {total} 条", self.src)

    def test_uses_shared_total_pages_fn(self):
        self.assertIn("adminTotalPages(total, pageSize)", self.src)

    def test_loading_disables_both(self):
        self.assertIn("|| loading", self.src)


class UsersPanelContractTests(unittest.TestCase):
    def setUp(self):
        self.src = read("components/samelabs/UsersPanel.tsx")

    def test_page_size_50(self):
        self.assertIn('limit: String(PAGE_SIZE)', self.src)

    def test_url_params(self):
        self.assertIn('searchParams.get("q")', self.src)
        self.assertIn('parseAdminPage(searchParams.get("page"))', self.src)

    def test_offset_conversion(self):
        self.assertIn("adminOffset(page)", self.src)

    def test_overflow_clamp(self):
        self.assertIn("page > totalPages", self.src)
        self.assertIn("router.replace", self.src)

    def test_mutation_reload_keeps_url_state(self):
        self.assertIn("appliedQRef.current.trim()", self.src)
        self.assertIn("pageRef.current", self.src)

    def test_race_guard(self):
        self.assertIn("seqRef", self.src)

    def test_search_submit_page1(self):
        self.assertIn("navigateTo(q, 1)", self.src)


class ReactionsPanelContractTests(unittest.TestCase):
    def setUp(self):
        self.src = read("components/samelabs/ReactionsPanel.tsx")

    def test_status_filter_from_url(self):
        self.assertIn('rawStatus === "visible" || rawStatus === "hidden"', self.src)

    def test_status_change_resets_page(self):
        self.assertIn("navigateTo(s, 1)", self.src)

    def test_moderation_reload_keeps_filter(self):
        self.assertIn('statusRef.current !== "all"', self.src)
        self.assertIn('params.set("status", statusRef.current)', self.src)

    def test_filtered_empty_page_clamp(self):
        """mutation 后当前页空且 total>0 → 回最后有效页。"""
        reload_fn = self.src[self.src.index("async function reload"):self.src.index("async function toggle")]
        self.assertIn("pageRef.current > totalPages", reload_fn)
        self.assertIn("router.replace", reload_fn)

    def test_filter_buttons_not_select(self):
        self.assertIn('<select', self.src.replace("<selectHidden", "")) if False else None
        self.assertNotIn("<select", self.src)


class SkillsPanelContractTests(unittest.TestCase):
    def setUp(self):
        self.src = read("components/samelabs/SkillsAdminPanel.tsx")

    def test_page_size_50_not_100(self):
        self.assertIn("String(PAGE_SIZE)", self.src)
        self.assertNotIn('limit: "100"', self.src)

    def test_url_roundtrip_params(self):
        self.assertIn('searchParams.get("q")', self.src)
        self.assertIn('searchParams.get("visibility")', self.src)
        self.assertIn('parseAdminPage(searchParams.get("page"))', self.src)

    def test_filter_resets_page(self):
        self.assertIn("navigateTo(appliedQ, v, 1)", self.src)

    def test_delete_reload_clamp(self):
        reload_fn = self.src[self.src.index("async function reload"):self.src.index("async function setVis")]
        self.assertIn("pageRef.current > totalPages", reload_fn)

    def test_offset_used(self):
        self.assertIn("adminOffset(page)", self.src)
        self.assertIn("adminOffset(pageRef.current)", self.src)


class AdminApiContractTests(unittest.TestCase):
    """Batch 1 契约仍成立的行为守卫 (源码级, 不依赖 git history)。

    旧的 NoTouchGuardTests (固定 base→HEAD git diff 白名单) 已删除:
    "某历史 Batch 当时只改哪些文件"是一次性验收约束, 不是永久 runtime contract;
    fetch-depth=1 checkout 下历史 commit 缺失还会产生假绿。
    """

    def test_admin_api_list_contract_shape(self):
        """/admin/users 与 /admin/reactions 仍是 {total, items} + limit/offset 契约。"""
        admin = (ROOT / "api" / "admin.py").read_text(encoding="utf-8")
        self.assertIn('"total"', admin)
        self.assertIn('"items"', admin)
        self.assertIn("offset: int = Query(0, ge=0)", admin)

    def test_self_protection_intact(self):
        admin = (ROOT / "api" / "admin.py").read_text(encoding="utf-8")
        self.assertIn("不能停用当前管理员账号", admin)
        self.assertIn("不能移除自己的管理员权限", admin)


if __name__ == "__main__":
    unittest.main()
