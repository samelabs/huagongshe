"""Admin privileged-action confirmation 契约测试 (Batch 1)。

纯源码契约 — 无外部依赖, 任何环境可跑:
1. WorkersPanel: 停用走 pendingDisableWorker 确认态, 确认前无 PATCH; 启用直接执行。
2. UsersPanel: 角色变更走 pendingRole 确认态, 确认前无 PATCH。
3. 用户停用 effect 文案事实语义 (sessions 注销 + AI Key 删除 + 不恢复)。
4. 后端 self-protection (admin.py 409) 存在。

运行: python -m unittest tests.test_admin_confirm_batch1 -v
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
API = ROOT / "api"


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def workers_panel() -> str:
    return read(WEB / "components" / "samelabs" / "WorkersPanel.tsx")


def users_panel() -> str:
    return read(WEB / "components" / "samelabs" / "UsersPanel.tsx")


def i18n() -> str:
    return read(WEB / "lib" / "i18n" / "locales" / "zh-CN.ts")


class WorkerDisableConfirmation(unittest.TestCase):
    """Worker 停用必须经过确认态; 启用不需要。"""

    def test_pending_state_exists(self):
        src = workers_panel()
        self.assertIn("pendingDisableWorker", src)

    def test_disable_button_does_not_patch_directly(self):
        src = workers_panel()
        # 停用按钮必须走 setPendingDisableWorker, 不得直接调用 setEnabled(row, false)
        self.assertIn("setPendingDisableWorker(w)", src)
        self.assertNotIn("setEnabled(w, !w.enabled)", src)

    def test_enable_path_direct_no_confirmation(self):
        src = workers_panel()
        # 启用保持直接 setEnabled(row, true), 无确认态介入
        self.assertIn("setEnabled(w, true)", src)

    def test_confirm_executes_patch_only_from_pending(self):
        src = workers_panel()
        # setEnabled 是唯一 PATCH 入口; 确认函数读取 pendingDisableWorker 后委托 setEnabled(row, false)
        patch_idx = src.find("apiPatch(")
        set_enabled_idx = src.find("async function setEnabled")
        self.assertGreater(patch_idx, -1)
        self.assertGreater(patch_idx, set_enabled_idx)
        self.assertIn("await setEnabled(row, false)", src)

    def test_no_false_claims_in_confirmation(self):
        src = workers_panel() + i18n()
        # 停用确认不得声称杀死进程/终止任务
        for banned in ("杀死", "终止正在运行", "立即终止", "删除该 worker"):
            self.assertNotIn(banned, src)
        # 新产品契约(E9-A): 安全删除 Worker 是明确功能;
        # 文案必须说明边界(仅无进行中任务, 历史记录保留)。
        self.assertIn("删除 Worker", i18n())
        self.assertIn("没有进行中任务", i18n())
        self.assertIn("历史完成记录保留", i18n())

    def test_worker_delete_has_confirmation(self):
        """删除必须经过确认态: 按钮 setPendingDeleteWorker 先于 DELETE。"""
        src = workers_panel()
        self.assertIn("pendingDeleteWorker", src)
        self.assertIn("setPendingDeleteWorker(w)", src)
        # 确认函数是唯一 DELETE 入口
        self.assertIn("apiDelete(`/admin/workers/${row.worker_id}`)", src)

    def test_worker_delete_409_shows_reason(self):
        """409(有活动任务)时展示服务端原因, 不静默失败。"""
        src = workers_panel()
        self.assertIn("e.status === 409", src)
        self.assertIn("e.detail", src)


class UserRoleConfirmation(unittest.TestCase):
    """角色变更 (提升/降级) 都必须经过确认态。"""

    def test_pending_role_state_exists(self):
        src = users_panel()
        self.assertIn("pendingRole", src)

    def test_role_button_opens_confirmation_not_patch(self):
        src = users_panel()
        # 角色按钮进入确认态, 不得直接调 toggleRole
        self.assertIn("setPendingRole(u)", src)
        self.assertNotIn("onClick={() => toggleRole(u.id, u.role)}", src)

    def test_both_directions_have_effect_copy(self):
        i18n_src = i18n()
        self.assertIn("userPromoteEffect", i18n_src)
        self.assertIn("userDemoteEffect", i18n_src)
        self.assertIn("获得平台管理权限", i18n_src)
        self.assertIn("失去平台管理权限", i18n_src)

    def test_patch_only_in_confirm_function(self):
        src = users_panel()
        # 角色 PATCH 逻辑只出现在确认执行函数内
        confirm_idx = src.find("pendingRole")
        patch_idx = src.find("/role`, JSON.stringify")
        self.assertGreater(patch_idx, -1)
        self.assertGreater(patch_idx, confirm_idx)


class UserDisableEffectWording(unittest.TestCase):
    """停用提示必须表达事实: 注销会话 + 删除 AI Key + 重新启用不恢复。"""

    def test_effect_copy_factual(self):
        i18n_src = i18n()
        self.assertIn("userDisableEffect", i18n_src)
        for fact in ("会话", "AI Key", "不会恢复"):
            self.assertIn(fact, i18n_src)
        # 不得暗示可恢复
        for banned in ("暂时失效", "恢复原有", "自动恢复"):
            self.assertNotIn(banned, i18n_src)


class BackendSelfProtection(unittest.TestCase):
    """后端 self-protection 保持存在 (前端不复制该逻辑)。"""

    def test_self_disable_protection(self):
        src = read(API / "admin.py")
        self.assertIn("不能停用当前管理员账号", src)
        self.assertIn("不能移除自己的管理员权限", src)


if __name__ == "__main__":
    unittest.main()
