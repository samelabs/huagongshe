"""A3 最小实施验收测试 (0912)。

Users:
1. q 真正传入现有 /users?q=(组件源断言: params.set("q", ...))
2. 空 q 恢复默认列表(组件源断言: 空 q 不带参数)
3. 不再出现 users.length 当"总用户数"(i18n userShownCount 语义)
4. disable 必须经过确认(组件源断言: setPendingDisable 先于 PATCH)
5. cancel 不发 PATCH(对话框 backdrop/取消按钮只 setPendingDisable(null))
6. confirm 后沿用现有 PATCH(/users/{id}/status)
7. self protection 不改(后端 409 逻辑零改动 — diff 级断言)

Skills:
1. delete 必须经过确认(setPendingDelete 先于 DELETE)
2. cancel 不发 DELETE
3. confirm 后沿用现有 DELETE(/admin/skills/{id})
4. 确认对象显示 title/slug
5. 无新增第二套删除状态(无 soft-delete 字段)

后端: 本轮零后端改动 — 断言 api/admin.py 无新增 endpoint。
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(p: str) -> str:
    return (ROOT / p).read_text(encoding="utf-8")


class UsersPanelTests(unittest.TestCase):
    def setUp(self):
        self.src = read("web/components/samelabs/UsersPanel.tsx")

    def test_q_wired_to_existing_endpoint(self):
        """验收1: q 传入现有 GET /users?q=, 不新增后端。"""
        self.assertIn('params.set("q", appliedQ.trim())', self.src)
        self.assertIn("`/admin/users?${params}`", self.src)

    def test_empty_q_default_list(self):
        """验收2: 空 q 不带参数(默认列表)。"""
        self.assertIn('if (appliedQ.trim()) params.set("q", appliedQ.trim())', self.src)

    def test_count_uses_total_not_pagelen(self):
        """验收3(Batch2 修订): 计数语义 = URL 条件下 total, 不用页内长度冒充。"""
        self.assertIn('搜索 "${appliedQ}" · 共 ${total} 条', self.src)
        self.assertIn('共 ${total} 条', self.src)
        self.assertNotIn("userShownCount", self.src)

    def test_disable_requires_confirm(self):
        """验收4+5: disable 先 setPendingDisable; cancel 只关对话框。"""
        self.assertIn("setPendingDisable(u)", self.src)   # active→打开确认, 非直接 PATCH
        self.assertIn('onClick={() => setPendingDisable(null)}', self.src)
        # 确认框内才有 status: "disabled" 的 PATCH
        confirm_block = self.src[self.src.index("async function confirmDisable"):]
        self.assertIn("/status", confirm_block)
        # 主列表按钮路径不含 disabled PATCH(只有 enable active)
        main_block = self.src[:self.src.index("async function confirmDisable")]
        self.assertIn('status: "active"', main_block)
        self.assertNotIn('status: "disabled"', main_block)

    def test_confirm_uses_existing_patch(self):
        """验收6: 沿用现有 PATCH /users/{id}/status。"""
        self.assertIn("apiPatch(`/admin/users/${pendingDisable.id}/status`", self.src)

    def test_disable_confirm_names_user(self):
        i18n = read("web/lib/i18n/locales/zh-CN.ts")
        self.assertIn("userDisableConfirm: (username: string, email: string)", i18n)
        # 事实语义: 注销全部会话 + 删除 AI Key + 重新启用不恢复
        self.assertIn("userDisableEffect: '停用会注销该用户全部会话并删除其现有 AI Key；重新启用账号不会恢复这些 Key。'", i18n)


class UsersSearchStateContractTests(unittest.TestCase):
    """q(draft)/URL q(已应用) 双状态契约 — Batch 2 后 URL 是唯一已应用真相源。"""

    def setUp(self):
        self.src = read("web/components/samelabs/UsersPanel.tsx")

    def _between(self, start_marker: str, end_marker: str) -> str:
        i = self.src.index(start_marker)
        return self.src[i:self.src.index(end_marker, i)]

    def test_two_states_declared(self):
        """draft 是 state; applied 来自 URL (不是第二套 state)。"""
        self.assertIn('const [q, setQ] = useState(appliedQ);', self.src)
        self.assertIn('searchParams.get("q")', self.src)
        self.assertNotIn('const [appliedQ, setAppliedQ] = useState', self.src,
                         "appliedQ 不得再是独立 state (URL 是唯一真相源)")

    def test_draft_edit_does_not_apply(self):
        """契约1: 仅编辑输入框不发请求。"""
        onchange = [l for l in self.src.split("\n") if "onChange" in l and "setQ" in l][0]
        self.assertNotIn("load(", onchange)
        self.assertNotIn("navigateTo(", onchange)

    def test_draft_syncs_from_url(self):
        """契约: 返回/前进后退时 draft 跟随 URL q。"""
        self.assertIn("useEffect(() => { setQ(appliedQ); }, [appliedQ]);", self.src)

    def test_search_submit_resets_page(self):
        """契约: 搜索提交 = 应用 draft + 回第 1 页, 走 URL。"""
        submit_fn = self._between("function submitSearch", "async function reload")
        self.assertIn("navigateTo(q, 1)", submit_fn)

    def test_reload_uses_url_state(self):
        """reload 与当前 URL 一致, 不被 draft 污染。"""
        self.assertIn("params.set(\"q\", appliedQRef.current.trim())", self.src)
        self.assertNotIn('params.set("q", q.trim())', self.src)

    def test_empty_q_url_clean(self):
        """契约: 默认值不写 URL (page=1/q 空时 URL 干净)。"""
        nav = self._between("function navigateTo", "function submitSearch")
        self.assertIn("if (nextQ.trim()) next.set", nav)
        self.assertIn("if (nextPage > 1) next.set", nav)


class SkillsPanelTests(unittest.TestCase):
    def setUp(self):
        self.src = read("web/components/samelabs/SkillsAdminPanel.tsx")

    def test_delete_requires_confirm(self):
        """验收1+2: 按钮 setPendingDelete; cancel 只关对话框。"""
        self.assertIn("onClick={() => setPendingDelete(s)}", self.src)
        self.assertIn('onClick={() => setPendingDelete(null)}', self.src)
        # 直接 removeSkill 只出现在确认框 confirm 按钮内
        self.assertNotIn("onClick={() => removeSkill(s.id)}", self.src)

    def test_confirm_uses_existing_delete(self):
        """验收3: 沿用现有 DELETE /admin/skills/{id}, 无第二套状态。"""
        self.assertIn("apiDelete(`/admin/skills/${id}`)", self.src)
        self.assertNotIn("soft", self.src.lower().replace("software", ""))

    def test_confirm_shows_title_slug(self):
        """验收4: 确认对象 title/slug。"""
        i18n = read("web/lib/i18n/locales/zh-CN.ts")
        self.assertIn("skillDeleteConfirm: (title: string, slug: string)", i18n)
        self.assertIn("删除不可恢复", i18n)


class BackendContractTests(unittest.TestCase):
    """A3 后端守卫 — 直接源码契约, 不做历史 git-diff 断言。

    旧的 BackendUntouchedTests 用固定 base ea8fe8b -> 7bb67df 的 git diff 白名单:
    属于当轮验收约束而非永久 contract, 且 Actions fetch-depth=1 下历史 commit
    缺失 + subprocess 不查 returncode 会产生假绿。已删除, 保留真实业务断言:
    """

    def test_self_protection_intact(self):
        """验收7: 管理员自保规则仍在后端。"""
        admin = read("api/admin.py")
        self.assertIn("不能停用当前管理员账号", admin)
        self.assertIn("不能移除自己的管理员权限", admin)

    def test_no_soft_delete_in_skills_delete(self):
        """A3 技能删除仍是硬删除 (无 soft-delete 第二套状态)。"""
        admin = read("api/admin.py")
        self.assertIn("@router.delete(\"/skills/{skill_id}\"", admin)


if __name__ == "__main__":
    unittest.main()
