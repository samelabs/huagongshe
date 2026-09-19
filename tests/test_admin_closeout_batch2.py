"""Admin 收口 Batch 2 契约测试 (stacked closeout)。

1. ConfigPanel 保存不得覆盖其他未保存 draft
   - save(entry) 的 PUT body 必须是该 entry 的当前 draft
   - 保存成功后不得再次 GET /admin/config (全量 reload 会整体替换 entries)
   - entries 只允许两条写入路径: 初始 useEffect 加载 + updateValue 字段级合并
   - dead helper reload()/await reload() 必须保持删除 (回归闸门)

2. Dashboard 收口 (E9-A 新契约)
   - 后端不再为首页计算 sessions/tokens/statistics/chemicals
   - 前端仅保留 用户 / 用户反应 / 磁盘 三卡
   - worker "最近活跃" 语义仍合法保留
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent

CONFIG_PANEL = "web/components/samelabs/ConfigPanel.tsx"
I18N = "web/lib/i18n.ts"
DASHBOARD = "web/components/samelabs/Dashboard.tsx"
ADMIN_API = "api/admin.py"

SAVE_SIGNATURE = "async function save(entry: ConfigEntry)"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def strip_comments(src: str) -> str:
    """去掉 JS 注释, 使结构性断言只针对真实代码。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"^\s*//.*$", "", src, flags=re.M)
    return src


def fn_body(src: str, signature: str) -> str:
    """按大括号配对取出函数体 (从 signature 起至其闭合大括号)。"""
    i = src.index(signature)
    depth = 0
    started = False
    for j in range(i, len(src)):
        ch = src[j]
        if ch == "{":
            depth += 1
            started = True
        elif ch == "}":
            depth -= 1
            if started and depth == 0:
                return src[i:j + 1]
    raise AssertionError(f"未找到闭合函数体: {signature}")


class ConfigSaveDraftPreservationTests(unittest.TestCase):
    """保存 A 不得覆盖 B 的 draft。"""

    def setUp(self):
        self.raw = read(CONFIG_PANEL)
        self.src = strip_comments(self.raw)
        self.save = fn_body(self.src, SAVE_SIGNATURE)

    def test_put_body_is_current_draft(self):
        """PUT body 必须是该 entry 当前本地 draft (非服务器回读值)。"""
        self.assertIn(
            "apiPut(`/admin/config/${entry.namespace}/${entry.key}`, JSON.stringify(entry.value))",
            self.save,
        )

    def test_save_success_path_does_not_refetch_config(self):
        """回归闸门: 保存成功路径不得再次 GET /admin/config。

        历史上 save() 在 setSaved 之后 await reload(), reload 里 setEntries(data)
        会把 A、B 的本地 draft 一起用服务器旧值覆盖。
        """
        self.assertNotIn("apiGet", self.save)
        self.assertNotIn("reload", self.save)
        self.assertNotIn("setEntries", self.save)

    def test_save_marks_saved_without_state_replacement(self):
        """成功路径只标记 saved 状态, 不触碰 entries。"""
        self.assertIn("setSaved(", self.save)
        tail = self.save[self.save.index("setSaved("):]
        for forbidden in ("apiGet", "reload", "setEntries", "await fetch"):
            self.assertNotIn(forbidden, tail)

    def test_no_global_reload_helper_remains(self):
        """reload() 已无调用, 必须保持删除 (dead helper 不得复活)。"""
        self.assertNotIn("async function reload", self.src)
        self.assertNotIn("await reload()", self.src)
        self.assertNotIn("reload(", self.src)

    def test_entries_written_only_by_mount_load_and_field_merge(self):
        """entries 写入点唯一化: mount 加载 + updateValue 字段级合并。"""
        occurrences = [m.start() for m in re.finditer(r"setEntries\(", self.src)]
        self.assertEqual(len(occurrences), 2, "entries 出现第三条写入路径, 可能整体替换: %r" % occurrences)

        mount = fn_body(self.src, "useEffect(() => {")
        updater = fn_body(self.src, "function updateValue(")
        for pos in occurrences:
            in_mount = self.src.index("useEffect(() => {") <= pos <= self.src.index("useEffect(() => {") + len(mount)
            in_updater = self.src.index("function updateValue(") <= pos <= self.src.index("function updateValue(") + len(updater)
            self.assertTrue(in_mount or in_updater, "setEntries 出现在非预期位置 (offset=%d)" % pos)

    def test_update_value_merges_single_field_only(self):
        """updateValue 只按 namespace+key 合并单字段, 不重建整个数组元素集合。"""
        updater = fn_body(self.src, "function updateValue(")
        self.assertIn("prev.map(", updater)
        self.assertIn("[field]: value", updater)

    def test_initial_load_fetches_config_once(self):
        """页面初始加载仍走 useEffect -> apiGet('/admin/config'), 且为本文件唯一 GET。"""
        self.assertEqual(self.src.count('apiGet<ConfigEntry[]>(`/admin/config`)'), 1)


class DashboardScopeTests(unittest.TestCase):
    """E9-A 契约: 首页轻量化 —— 无管理入口/决策用途的统计连查询一起删。"""

    def setUp(self):
        self.api = read(ADMIN_API)
        self.i18n = read(I18N)
        self.dashboard = read(DASHBOARD)

    def test_backend_no_sessions_tokens_chemicals_queries(self):
        body = fn_body(self.api, "async def dashboard(")
        for gone in ("community.sessions", "user_api_tokens", "chemistry.statistics",
                     "metric='chemicals'"):
            self.assertNotIn(gone, body, f"dashboard 查询应已删除: {gone}")

    def test_backend_keeps_users_reactions_disk(self):
        body = fn_body(self.api, "async def dashboard(")
        self.assertIn("count(*) FROM community.users", body)
        self.assertIn("created_by_user_id IS NOT NULL", body)
        self.assertIn("disk_usage", body)

    def test_frontend_only_three_cards(self):
        for card in ("statUsers", "statUserReactions", "statDisk"):
            self.assertIn(f"t.admin.{card}", self.dashboard)
        for gone in ("statSessions", "statTokens", "statAllReactions", "statChemicals"):
            self.assertNotIn(f"t.admin.{gone}", self.dashboard)
            self.assertNotIn(f"{gone}:", self.i18n)

    def test_dashboard_no_expensive_pipeline_hookup(self):
        """首页不得触发 Pipeline/governance 聚合。"""
        self.assertNotIn("/admin/pipeline", self.dashboard)

    def test_other_activity_wording_not_banned(self):
        """不全局禁止"活跃": worker 最近活跃 等语义合法, 必须保留。"""
        self.assertIn("workerLastSeen", self.i18n)
        self.assertIn("最近活跃", self.i18n)


if __name__ == "__main__":
    unittest.main()
