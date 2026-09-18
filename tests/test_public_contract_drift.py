"""E7 §9 — 公开契约 drift guard: 只守"已经宣称的事实"。

守:
1. web/public/llms.txt 声明的 MCP 工具数量 == 真实 MCP tool surface;
2. llms.txt 声明的每个 HTTP 端点(方法 + 路径)在真实路由表里存在;
3. 解析必须真的解析到内容(空解析 = 失败, 不允许静默通过)。

不做: 全量 OpenAPI 投影 / 第二份接口 catalog / 文档生成系统。
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

LLMS = REPO / "web" / "public" / "llms.txt"

_TOOL_COUNT_RE = re.compile(r"MCP 工具（(\d+) 个）")
_ENDPOINT_RE = re.compile(r"`(GET|POST|PUT|PATCH|DELETE) (/api/[^`?\s]*)")


def _norm_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{X}", path)


class LlmsTxtDeclaredFactsTests(unittest.TestCase):
    """llms.txt 是公开宣称面: 宣称的事实必须仍成立。"""

    def setUp(self) -> None:
        self.assertTrue(LLMS.is_file(), f"llms.txt 缺失: {LLMS}")
        self.text = LLMS.read_text(encoding="utf-8")

    def test_declared_mcp_tool_count_matches_actual_surface(self):
        m = _TOOL_COUNT_RE.search(self.text)
        self.assertIsNotNone(m, "llms.txt 未声明 MCP 工具数量")
        declared = int(m.group(1))
        from tests.test_api_contract_governance import _mcp_tool_names
        actual = _mcp_tool_names()
        self.assertEqual(declared, len(actual),
                         f"llms.txt 声明 {declared} 个, 实际 {len(actual)}: {sorted(actual)}")

    def test_declared_http_endpoints_still_exist(self):
        declared = {(meth, _norm_path(path))
                    for meth, path in _ENDPOINT_RE.findall(self.text)}
        self.assertGreaterEqual(len(declared), 8,
                                f"llms.txt 端点解析异常(过少): {sorted(declared)}")
        from tests.test_api_contract_governance import _app, _iter_routes
        actual = {(meth, _norm_path(path)) for meth, path in _iter_routes(_app())}
        missing = sorted(f"{m} {p}" for m, p in declared if (m, p) not in actual)
        self.assertEqual(missing, [], "llms.txt 声明的端点已不存在(公开宣称漂移)")

    def test_declared_endpoints_are_not_a_full_api_catalog(self):
        """guard 面是"宣称", 不是全量接口目录: 声明数必须远小于真实路由数。"""
        from tests.test_api_contract_governance import _app, _iter_routes
        declared = {(_norm_path(p)) for _, p in _ENDPOINT_RE.findall(self.text)}
        actual = {_norm_path(p) for _, p in _iter_routes(_app())}
        self.assertLess(len(declared), len(actual),
                        "llms.txt 不应变成全量接口目录")


if __name__ == "__main__":
    unittest.main()
