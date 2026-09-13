"""Batch 2 (admin pagination UI + URL state) 契约测试。

分层:
1. 纯函数 (lib/adminPagination.ts) — Node 直跑 tsc 输出后的 JS
2. 三面板源码契约 — URL 真相源 / PAGE_SIZE=50 / offset 换算 / clamp / mutation reload / 竞态
3. 共享 AdminPagination 组件 — 边界禁用契约

运行: python3 -m unittest tests.test_admin_pagination_ui -v
(纯函数部分先 npx tsc 编译 adminPagination.ts 到临时 JS 再 import)
"""

from __future__ import annotations

import json
import os
import subprocess
import shutil
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def read(p: str) -> str:
    return (WEB / p).read_text(encoding="utf-8")


def load_pagination_module():
    """tsc --module commonjs 编译 lib/adminPagination.ts 到 /tmp → .cjs → node require。

    产物经 require() 拿到真实 exports (PAGE_SIZE/parseAdminPage/adminOffset/adminTotalPages)。
    不改生产源码; 每次调用重新编译, 保证测的是当前源码。
    """
    src = WEB / "lib" / "adminPagination.ts"
    tsc_bin = WEB / "node_modules" / ".bin" / "tsc"
    out_dir = Path("/tmp/hgs-admin-pagination-test")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    js = subprocess.run(
        [str(tsc_bin), "lib/adminPagination.ts", "--target", "ES2020",
         "--module", "commonjs", "--esModuleInterop", "--skipLibCheck",
         "--outDir", str(out_dir)],
        cwd=WEB, capture_output=True, text=True, timeout=120,
    )
    cjs = out_dir / "adminPagination.js"
    if js.returncode != 0 or not cjs.exists():
        raise RuntimeError(f"tsc 编译失败: rc={js.returncode} {js.stderr[:500]}")
    # 项目 package.json type:module 可能使 .js 被 node 按 ESM 解析 → 复制为 .cjs
    dst = out_dir / "adminPagination.cjs"
    dst.write_text(cjs.read_text(encoding="utf-8"), encoding="utf-8")

    def run(exprs):
        """exprs: JS 表达式列表(以 m. 前缀引用模块), 返回 JSON 值列表。"""
        code = (
            f"const m = require({json.dumps(str(dst))});\n"
            "console.log(JSON.stringify([" + ",".join(exprs) + "]));"
        )
        r = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"node 执行失败: {r.stderr[:300]}")
        return json.loads(r.stdout.strip())

    return run


class PureFunctionTests(unittest.TestCase):
    """parseAdminPage / adminOffset / adminTotalPages (跑真实 tsc 编译产物)。"""

    @classmethod
    def setUpClass(cls):
        cls._run_fn = load_pagination_module()

    def setUp(self):
        self.run = type(self)._run_fn

    def test_page_size_is_50(self):
        self.assertEqual([50], self.run(["m.PAGE_SIZE"]))

    def test_parse_admin_page_valid(self):
        vals = self.run([
            'm.parseAdminPage(null)',
            'm.parseAdminPage("")',
            'm.parseAdminPage("1")',
            'm.parseAdminPage("2")',
            'm.parseAdminPage("10")',
        ])
        self.assertEqual([1, 1, 1, 2, 10], vals)

    def test_parse_admin_page_invalid_falls_to_1(self):
        bad = ["0", "-1", "abc", "1.5", "1e2", " 2", "NaN", "Infinity"]
        vals = self.run([f'm.parseAdminPage({json.dumps(b)})' for b in bad])
        self.assertEqual([1] * len(bad), vals, f"非法 page 应按 1 处理: {bad}")

    def test_admin_offset(self):
        vals = self.run([
            'm.adminOffset(1)',
            'm.adminOffset(2)',
            'm.adminOffset(10)',
            'm.adminOffset(1, 25)',
            'm.adminOffset(2, 25)',
        ])
        self.assertEqual([0, 50, 450, 0, 25], vals)

    def test_admin_total_pages(self):
        vals = self.run([
            'm.adminTotalPages(0)',
            'm.adminTotalPages(1)',
            'm.adminTotalPages(50)',
            'm.adminTotalPages(51)',
            'm.adminTotalPages(480)',
            'm.adminTotalPages(500)',
            'm.adminTotalPages(501)',
        ])
        self.assertEqual([1, 1, 1, 2, 10, 10, 11], vals)


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


class NoTouchGuardTests(unittest.TestCase):
    """Batch 2 禁改清单守卫。"""

    def test_forbidden_files_untouched_vs_batch1(self):
        diff = subprocess.run(
            ["git", "diff", "--name-only",
             "d621cd78ba1e849474542c343c3c9aad3d747a4d", "HEAD"],
            cwd=ROOT, capture_output=True, text=True,
        ).stdout.split()
        allowed = {
            "web/components/samelabs/UsersPanel.tsx",
            "web/components/samelabs/ReactionsPanel.tsx",
            "web/components/samelabs/SkillsAdminPanel.tsx",
            "web/components/samelabs/AdminPagination.tsx",
            "web/lib/adminPagination.ts",
            "web/app/globals.css",
            "tests/test_admin_a3_minimal.py",
            "tests/test_admin_pagination_ui.py",
        }
        illegal = [f for f in diff if f not in allowed]
        self.assertEqual([], illegal, f"超出 Batch 2 范围的文件改动: {illegal}")

    def test_admin_api_unchanged(self):
        """api/admin.py 本轮零改动 (Batch 1 契约冻结)。"""
        diff = subprocess.run(
            ["git", "diff", "--stat",
             "d621cd78ba1e849474542c343c3c9aad3d747a4d", "HEAD", "--", "api/"],
            cwd=ROOT, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual("", diff, f"api/ 不得改动: {diff}")


if __name__ == "__main__":
    unittest.main()
