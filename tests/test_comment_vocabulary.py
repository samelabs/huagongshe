"""注释词表检查器的单测：块注释全文识别与残句形态的正反例。

只测纯函数（块注释扫描与词表模式），不跑 git 差异 —— 主流程的
基线解析与文件遍历由 --all / --base 实跑验证。
"""
from __future__ import annotations

import unittest

from scripts.check_comment_vocabulary import (
    COMMENT_ONLY_PATTERNS,
    PATTERNS,
    _block_comment_texts,
    _comment_segment,
)


def _first_comment_hit(text: str) -> str | None:
    """注释正文命中的第一个注释段专用词表名；未命中返回 None。"""
    for name, pattern in PATTERNS:
        if name in COMMENT_ONLY_PATTERNS and pattern.search(text):
            return name
    return None


class BlockCommentScanTests(unittest.TestCase):
    """块注释从 /* 起到最近 */ 止，续行不要求以 * 开头。"""

    def test_continuation_lines_without_star_are_comments(self):
        text = (
            "/** 说明第一行\n"
            "这一行没有星号前缀也算注释\n"
            " * 传统星号续行\n"
            "*/\n"
            "export const k = 1;\n"
        )
        texts = _block_comment_texts(text)
        self.assertEqual(sorted(texts), [1, 2, 3, 4])
        self.assertIn("没有星号前缀", texts[2])
        self.assertNotIn("export", texts[4])

    def test_line_comment_slash_does_not_open_block(self):
        text = "// SUT: web/lib/i18n/locales/*.ts（真实实现）\nexport const k = 1;\n"
        self.assertEqual(_block_comment_texts(text), {})

    def test_glob_in_string_does_not_open_block(self):
        text = 'test("/mcp 与 /mcp/* 排除", () => {\n  expect(1).toBe(1);\n});\n'
        self.assertEqual(_block_comment_texts(text), {})

    def test_self_closing_inline_block_takes_only_inner_text(self):
        text = ".catch(() => { /* 静默：红点不显示 */ });\n"
        texts = _block_comment_texts(text)
        self.assertEqual(texts[1].strip(), "静默：红点不显示")
        self.assertNotIn("catch", texts[1])


class CommentSegmentTests(unittest.TestCase):
    """块注释行经 _comment_segment 取出正文（以缓存注入代替磁盘读取）。"""

    def test_block_line_returns_inner_text(self):
        import scripts.check_comment_vocabulary as C
        C._block_comment_lines._cache = {"fixture.tsx": {3: " 续行正文"}}
        try:
            self.assertEqual(_comment_segment("fixture.tsx", "  任意行", 3), " 续行正文")
        finally:
            C._block_comment_lines._cache = {}

    def test_code_line_is_not_comment(self):
        import scripts.check_comment_vocabulary as C
        C._block_comment_lines._cache = {"fixture.tsx": {}}
        try:
            self.assertIsNone(_comment_segment("fixture.tsx", "foo()", 1))
        finally:
            C._block_comment_lines._cache = {}


class ResiduePatternTests(unittest.TestCase):
    """残句形态正反例：命中的是删词残留，不命中合法写法。"""

    def test_empty_fullwidth_parens_next_to_hanzi(self):
        self.assertEqual(_first_comment_hit("概览重做（）后改为单行"), "残句空括号")

    def test_paren_slash_space(self):
        self.assertEqual(_first_comment_hit("安全设置(/ 修改密码)"), "括号内斜杠残句")

    def test_paren_slash_only(self):
        self.assertEqual(_first_comment_hit("超时关怀(/)"), "括号内斜杠残句")

    def test_leading_slash_number(self):
        self.assertEqual(_first_comment_hit("/14 边缘缓存规则"), "行首斜杠编号")

    def test_function_call_not_hit(self):
        self.assertIsNone(_first_comment_hit("调用 foo() 取值"))

    def test_path_in_parens_not_hit(self):
        self.assertIsNone(_first_comment_hit("排除路径(/api/x) 不改写"))

    def test_sql_named_param_not_hit(self):
        self.assertIsNone(_first_comment_hit("绑定 (:param) 具名参数"))


if __name__ == "__main__":
    unittest.main()
