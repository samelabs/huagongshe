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
        self.assertIn('params.set("q", query.trim())', self.src)
        self.assertIn("`/admin/users?${params}`", self.src)

    def test_empty_q_default_list(self):
        """验收2: 空 q 不带参数(默认列表)。"""
        self.assertIn('if (e.target.value === "") load("");', self.src)
        self.assertIn('if (query.trim()) params.set', self.src)

    def test_count_not_total(self):
        """验收3: 计数语义=当前显示 N 条, 不称总数。"""
        self.assertIn("userShownCount(users.length", self.src)
        self.assertNotIn("userCount(users.length)", self.src)
        i18n = read("web/lib/i18n.ts")
        self.assertIn("当前显示 ${n} 条", i18n)
        self.assertIn("当前显示 ${n} 条搜索结果", i18n)

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
        i18n = read("web/lib/i18n.ts")
        self.assertIn("userDisableConfirm: (username: string, email: string)", i18n)
        self.assertIn("userDisableEffect: '停用后将注销该用户会话并撤销 AI Key。'", i18n)


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
        i18n = read("web/lib/i18n.ts")
        self.assertIn("skillDeleteConfirm: (title: string, slug: string)", i18n)
        self.assertIn("删除不可恢复", i18n)


class BackendUntouchedTests(unittest.TestCase):
    def test_no_new_endpoint_and_self_protection_intact(self):
        """验收7+无新 endpoint: 后端 admin.py 本轮零改动(与 base 比)。"""
        import subprocess
        diff = subprocess.run(
            ["git", "diff", "--name-only", "ea8fe8b125e751bc5e4e4838e00cb98f5dfd80b9", "HEAD"],
            cwd=ROOT, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual("", diff.replace("web/components/samelabs/UsersPanel.tsx", "")
                         .replace("web/components/samelabs/SkillsAdminPanel.tsx", "")
                         .replace("web/lib/i18n.ts", "").replace("web/app/globals.css", "")
                         .replace("tests/test_admin_a3_minimal.py", "").strip(),
                         f"超出授权范围的文件改动: {diff}")
        admin = read("api/admin.py")
        self.assertIn("不能停用当前管理员账号", admin)
        self.assertIn("不能移除自己的管理员权限", admin)


if __name__ == "__main__":
    unittest.main()
