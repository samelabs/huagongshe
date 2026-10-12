"""v1.7.0 收口补正契约测试(L2/L3 错误分类 + 写入/刷新分离)。

源码级契约断言(与 tests/test_notes_ui_contract.py 同风格, 零依赖可跑):
- NoteEditor: 401/429 状态分支先于 kind 映射; 400+kind 五语言分类;
  未知失败安全回退 notesSaveFailed。
- SkillsPanel: 401/403/429 专用键, 400/409 透出业务 detail, 5xx 与网络
  错误落本地化通用失败; 不挪用搜索专用 errLoginRequired。
- SkillsPanel: 写请求成功即成功 — 刷新失败走 skillRefreshFailed 提示,
  不进入 uploadError(不反向报上传/删除失败)。
- ApiError: 结构化 {message, kind} detail 解析(detail/detailKind)。
- 五语言字典: 新增键(notesSessionExpired/skillLoginRequired/
  skillForbidden/skillRateLimited/skillRefreshFailed)全部存在且 key 树一致。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCALES = ["zh-CN", "en", "ja", "ko", "de"]


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


class NoteEditorErrorBranchContract(unittest.TestCase):
    def test_status_branches_before_kind_mapping(self):
        src = _read("web/components/workbench/NoteEditor.tsx")
        self.assertIn("err.status === 401", src, "401 必须有专用分支")
        self.assertIn("err.status === 429", src, "429 必须有专用分支")
        self.assertIn("t.me.notesSessionExpired", src, "401 → 会话过期提示")
        self.assertIn("t.search.errRateLimit", src, "429 → 限流提示")
        # 401/429 分支必须先于 kind 映射(顺序锁)
        self.assertLess(
            src.index("err.status === 401"),
            src.index("err.detailKind as keyof"),
            "状态分支必须先于 kind 映射",
        )
        # kind 映射仅在 400 分支内生效
        self.assertIn("err.status === 400 && err.detailKind", src)

    def test_unknown_failure_safe_fallback(self):
        src = _read("web/components/workbench/NoteEditor.tsx")
        # 非 ApiError / 无 kind 的 400 / 其他状态 → notesSaveFailed 回退
        self.assertGreaterEqual(src.count("t.me.notesSaveFailed"), 2)
        self.assertNotIn("setError(err.message", src, "不得直出技术 message")
        self.assertNotIn("setError(err.detail", src, "不得无条件直出 detail")


class SkillsPanelErrorContract(unittest.TestCase):
    def setUp(self):
        self.src = _read("web/components/workbench/panels/SkillsPanel.tsx")

    def test_status_specific_messages(self):
        self.assertIn("error.status === 401", self.src)
        self.assertIn("error.status === 403", self.src)
        self.assertIn("error.status === 429", self.src)
        self.assertIn("t.me.skillLoginRequired", self.src, "401 专用键")
        self.assertIn("t.me.skillForbidden", self.src, "403 专用键")
        self.assertIn("t.me.skillRateLimited", self.src, "429 专用键")

    def test_business_detail_only_400_409(self):
        # 业务校验 detail 仅 400/409 透出; 不得对所有 4xx 泄露
        self.assertIn('error.status === 400 || error.status === 409', self.src)

    def test_5xx_and_network_localized_generic(self):
        self.assertIn("error.status >= 500", self.src, "5xx 分支")
        self.assertIn("t.common.networkError", self.src, "本地化通用网络失败")
        self.assertNotIn("err.message", self.src.replace("error.message", ""),
                         "不得直出 err.message 内部路径")

    def test_no_search_specific_login_copy(self):
        # 不挪用搜索专用"结构检索需要登录"文案
        self.assertNotIn("errLoginRequired", self.src)

    def test_write_success_separated_from_refresh(self):
        # 写成功后刷新失败: 走 skillRefreshFailed 提示, 不进 uploadError
        self.assertIn("t.me.skillRefreshFailed", self.src)
        # 刷新 try/catch 与写 try/catch 分离(嵌套结构)
        self.assertGreaterEqual(self.src.count("} catch {"), 2,
                                "上传与删除各需一个刷新专用 catch")
        # 刷新失败 catch 内不得调用 setUploadError(不反向报写失败)
        for block in re.finditer(r"setUploadNotice\(t\.me\.skill(?:Uploaded|Deleted)\([^;]+\)\);(?:.|\n)*?\} catch \{\n((?:.|\n)*?)\n      \}", self.src):
            self.assertNotIn("setUploadError", block.group(1),
                             "刷新失败不得设 uploadError")


class ApiErrorStructuredDetailContract(unittest.TestCase):
    def test_message_kind_extraction(self):
        src = _read("web/lib/api.ts")
        self.assertIn("detailKind", src)
        self.assertIn('"message"', src.replace("message?", '"message"'))
        self.assertIn("kind", src)
        # 结构分支仅在字符串 detail 分支之后(兼容旧形态优先)
        self.assertLess(src.index('typeof inner === "string"'),
                        src.index("detailKind = kind"))


class DictionaryKeysContract(unittest.TestCase):
    NEW_KEYS = ["notesSessionExpired", "skillLoginRequired",
                "skillForbidden", "skillRateLimited", "skillRefreshFailed"]

    def test_new_keys_present_all_locales(self):
        for loc in LOCALES:
            src = _read(f"web/lib/i18n/locales/{loc}.ts")
            for key in self.NEW_KEYS:
                self.assertIn(key, src, f"{loc} 缺 {key}")

    def test_me_key_tree_identical_across_locales(self):
        trees = {}
        for loc in LOCALES:
            src = _read(f"web/lib/i18n/locales/{loc}.ts").split("  me: {", 1)[1]
            section = src.split("\n  },", 1)[0]
            trees[loc] = set(re.findall(r"^    ([A-Za-z0-9_]+):", section, re.M))
        base = trees["zh-CN"]
        for loc in LOCALES:
            self.assertEqual(trees[loc], base, loc)
        for key in self.NEW_KEYS + ["notesRefError", "notesSaveFailed"]:
            self.assertIn(key, base)


class NotesBackendKindContract(unittest.TestCase):
    def test_reference_error_kinds(self):
        svc = _read("api/services/notes.py")
        for kind in ("chemical_not_found", "reaction_not_accessible",
                     "public_requires_public"):
            self.assertIn(f'kind="{kind}"', svc)
        adapter = _read("api/notes.py")
        self.assertGreaterEqual(
            adapter.count('{"message": str(exc), "kind": exc.kind}'), 2,
            "POST/PUT 两处 400 均须结构化 detail")


if __name__ == "__main__":
    unittest.main()
